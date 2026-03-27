#!/usr/bin/env python3
"""
全球热门资讯聚合 + 飞书每日推送
覆盖: 金融、人工智能、政治、军事、科技、经济
数据源: 国际RSS + Firecrawl搜索(中英文) + 同花顺7x24
"""

import os, json, re, time, subprocess, sys, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import requests

BJT = timezone(timedelta(hours=8))
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")

# ──────────────────── 搜索查询配置(中文+英文) ────────────────────

SEARCH_QUERIES = {
    "金融财经": [
        "全球金融市场 股市 美股 A股 今日",
        "央行 利率 汇率 黄金 原油 最新",
        "global financial markets stocks today",
        "Federal Reserve interest rate oil gold price",
    ],
    "人工智能": [
        "人工智能 AI 大模型 最新进展",
        "AI芯片 算力 科技公司 突破",
        "artificial intelligence AI breakthrough latest",
        "OpenAI Google AI chip Nvidia latest news",
    ],
    "国际政治": [
        "国际政治 外交 峰会 谈判 最新",
        "中美关系 欧盟 全球治理",
        "world politics diplomacy summit latest",
        "US China relations EU geopolitics",
    ],
    "军事安全": [
        "军事冲突 战争 地缘政治 安全",
        "国防 武器 演习 军事部署",
        "military conflict war defense latest",
        "NATO Ukraine Russia Middle East conflict",
    ],
    "科技前沿": [
        "科技突破 量子计算 航天 新技术 2026",
        "technology breakthrough quantum space robotics",
    ],
}

# ──────────────────── 国际RSS源 ────────────────────

INTL_RSS_FEEDS = {
    "金融财经": [
        ("https://news.google.com/rss/search?q=finance+stock+market&hl=en&gl=US&ceid=US:en", "Google Finance"),
        ("https://feeds.bbci.co.uk/news/business/rss.xml", "BBC Business"),
        ("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "NYT Business"),
        ("https://www.cnbc.com/id/10001147/device/rss/rss.html", "CNBC"),
        ("https://feeds.reuters.com/reuters/businessNews", "Reuters Business"),
        ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664", "CNBC Finance"),
    ],
    "人工智能": [
        ("https://news.google.com/rss/search?q=artificial+intelligence+AI&hl=en&gl=US&ceid=US:en", "Google AI"),
        ("https://techcrunch.com/category/artificial-intelligence/feed/", "TechCrunch AI"),
        ("https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "The Verge AI"),
    ],
    "国际政治": [
        ("https://news.google.com/rss/search?q=world+politics+diplomacy&hl=en&gl=US&ceid=US:en", "Google World"),
        ("https://feeds.bbci.co.uk/news/world/rss.xml", "BBC World"),
        ("https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "NYT World"),
        ("https://www.aljazeera.com/xml/rss/all.xml", "Al Jazeera"),
        ("https://www.theguardian.com/world/rss", "The Guardian"),
    ],
    "军事安全": [
        ("https://news.google.com/rss/search?q=military+defense+conflict&hl=en&gl=US&ceid=US:en", "Google Defense"),
        ("https://feeds.bbci.co.uk/news/world/rss.xml", "BBC World"),
    ],
    "科技前沿": [
        ("https://news.google.com/rss/search?q=technology+breakthrough+science&hl=en&gl=US&ceid=US:en", "Google Tech"),
        ("https://feeds.bbci.co.uk/news/technology/rss.xml", "BBC Tech"),
        ("https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml", "NYT Tech"),
        ("https://www.wired.com/feed/rss", "Wired"),
    ],
}

# 同花顺7x24
THS_NEWS_URL = "https://news.10jqka.com.cn/tapp/news/push/stock/"

# 重要性关键词权重 (中英文)
IMPORTANCE_KW = {
    5: ['突发', '重大', '紧急', '央行', '美联储', 'Fed', '降息', '加息',
        '战争', '冲突', '制裁', '禁令', '崩盘', '熔断', '黑天鹅',
        'GPT-5', 'AGI', '核武', '导弹', '入侵', '政变', '停火',
        'breaking', 'urgent', 'crisis', 'war', 'invasion', 'ceasefire',
        'sanctions', 'crash', 'meltdown', 'nuclear', 'coup', 'emergency',
        'rate cut', 'rate hike', 'Federal Reserve'],
    3: ['利好', '利空', '暴涨', '暴跌', '政策', '监管', '峰会',
        '总统', '主席', '首相', 'AI', '芯片', '半导体', '量子',
        '石油', '黄金', '美元', '人民币', 'GDP', 'CPI', '非农',
        '选举', '外交', '条约', '联合国', '北约', 'NATO',
        'OpenAI', 'Google', 'Apple', '微软', '英伟达', '特斯拉',
        '油价', '通胀', '衰退', '涨停', '跌停',
        'president', 'summit', 'election', 'tariff', 'inflation',
        'recession', 'trillion', 'billion', 'surge', 'plunge',
        'S&P 500', 'Nasdaq', 'Dow Jones', 'Bitcoin', 'crypto',
        'Nvidia', 'Tesla', 'Microsoft', 'Amazon', 'Meta',
        'Pentagon', 'White House', 'Congress', 'EU', 'G7', 'G20',
        'OPEC', 'IMF', 'World Bank', 'WTO', 'UN'],
    1: ['上涨', '下跌', '发布', '合作', '投资', '融资', '上市',
        '报告', '数据', '预测', '趋势', '创新', '突破', '机器人',
        '无人机', '卫星', '航母', '演习', '部署',
        'rally', 'decline', 'launch', 'deal', 'partnership',
        'IPO', 'earnings', 'forecast', 'innovation', 'breakthrough',
        'robotics', 'satellite', 'spacecraft', 'quantum', 'chip'],
}


def _get(url, timeout=8):
    for i in range(2):
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return r
        except Exception:
            if i == 1:
                return None
            time.sleep(1)
    return None


# ──────────────────── Firecrawl 新闻搜索 ────────────────────

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
FIRECRAWL_SEARCH_URL = "https://api.firecrawl.dev/v1/search"


def search_firecrawl(query, category, limit=5):
    """通过 Firecrawl API 搜索新闻"""
    items = []
    # 优先用 MCP server (通过子进程调用自身)
    # 这里直接用 HTTP API
    if FIRECRAWL_API_KEY:
        try:
            headers = {"Authorization": f"Bearer {FIRECRAWL_API_KEY}"}
            payload = {
                "query": query,
                "limit": limit,
                "sources": [{"type": "news"}],
            }
            r = requests.post(FIRECRAWL_SEARCH_URL, json=payload,
                              headers=headers, timeout=15)
            data = r.json()
            for n in data.get("news", data.get("data", [])):
                title = n.get("title", "")
                if not title:
                    continue
                items.append({
                    "title": _clean(title),
                    "link": n.get("url", ""),
                    "summary": _clean(n.get("snippet", n.get("description", "")))[:200],
                    "source": _extract_source(n.get("url", "")),
                    "category": category,
                    "pub_date": n.get("date", ""),
                })
        except Exception as e:
            print(f"    Firecrawl API error: {e}")
    return items


def search_via_requests(query, category, limit=5):
    """通过搜狗新闻搜索"""
    items = []
    url = "https://news.sogou.com/news"
    params = {"query": query, "mode": 1, "sort": 1}
    r = _get(f"https://news.sogou.com/news?query={requests.utils.quote(query)}&mode=1&sort=1")
    if r:
        # 简单正则提取
        titles = re.findall(r'<h3[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r.text, re.S)
        for link, raw_title in titles[:limit]:
            title = _clean(raw_title)
            if title and len(title) > 5:
                items.append({
                    "title": title,
                    "link": link,
                    "summary": "",
                    "source": _extract_source(link),
                    "category": category,
                })
    return items


def _extract_source(url):
    """从URL提取来源域名"""
    if not url:
        return "未知"
    domain_map = {
        # 中文媒体
        'wallstreetcn': '华尔街见闻', 'sina.com': '新浪', 'sohu.com': '搜狐',
        'eastmoney': '东方财富', 'caixin': '财新', 'thepaper': '澎湃',
        'guancha': '观察者网', '36kr': '36氪', 'jfdaily': '解放日报',
        'finance.sina': '新浪财经', 'cls.cn': '财联社', 'yicai': '第一财经',
        'stcn.com': '证券时报', 'nbd.com': '每日经济新闻',
        # 国际媒体
        'bbc.com': 'BBC', 'bbc.co.uk': 'BBC',
        'reuters.com': 'Reuters路透社', 'apnews.com': 'AP美联社',
        'nytimes.com': 'NYT纽约时报', 'washingtonpost.com': 'WashPost华邮',
        'theguardian.com': 'Guardian卫报', 'ft.com': 'FT金融时报',
        'wsj.com': 'WSJ华尔街日报', 'economist.com': 'Economist经济学人',
        'bloomberg.com': 'Bloomberg彭博', 'cnbc.com': 'CNBC',
        'cnn.com': 'CNN', 'foxnews.com': 'Fox News',
        'aljazeera.com': 'Al Jazeera半岛', 'aljazeera.net': 'Al Jazeera半岛',
        'france24.com': 'France24', 'dw.com': 'DW德国之声',
        'nhk.or.jp': 'NHK', 'japantimes.co.jp': 'Japan Times',
        'scmp.com': 'SCMP南华早报', 'straitstimes.com': 'Straits Times海峡时报',
        'techcrunch.com': 'TechCrunch', 'theverge.com': 'The Verge',
        'wired.com': 'Wired', 'arstechnica.com': 'Ars Technica',
        'coindesk.com': 'CoinDesk', 'cointelegraph': 'CoinTelegraph',
        'voachinese': 'VOA', 'storm.mg': '风传媒', 'atvnews': 'ATV',
        'news.google.com': 'Google News',
        'politico.com': 'Politico', 'thehill.com': 'The Hill',
        'foreignaffairs.com': 'Foreign Affairs', 'foreignpolicy.com': 'Foreign Policy',
        'defensenews.com': 'Defense News', 'janes.com': 'Janes',
    }
    for key, name in domain_map.items():
        if key in url:
            return name
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.replace('www.', '').split('.')[0]
    except Exception:
        return "网络"


def _clean(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&[a-z]+;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ──────────────────── 国际RSS新闻抓取 ────────────────────

def fetch_rss_feed(url, source_name, category, limit=8):
    """解析单个RSS feed，返回新闻列表"""
    items = []
    try:
        r = requests.get(url, timeout=12,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"})
        if r.status_code != 200:
            return items
        root = ET.fromstring(r.content)
        # 处理 Atom 和 RSS 两种格式
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        # RSS 2.0 格式
        rss_items = root.findall('.//item')
        if not rss_items:
            # Atom 格式
            rss_items = root.findall('.//atom:entry', ns)
        for entry in rss_items[:limit]:
            # RSS 2.0
            title_el = entry.find('title')
            link_el = entry.find('link')
            desc_el = entry.find('description')
            pub_el = entry.find('pubDate')
            # Atom fallback
            if title_el is None:
                title_el = entry.find('atom:title', ns)
            if link_el is None:
                link_el = entry.find('atom:link', ns)
            if desc_el is None:
                desc_el = entry.find('atom:summary', ns)
            if pub_el is None:
                pub_el = entry.find('atom:published', ns) or entry.find('atom:updated', ns)

            title = ""
            if title_el is not None and title_el.text:
                title = _clean(title_el.text)

            link = ""
            if link_el is not None:
                link = link_el.text or link_el.get('href', '')

            summary = ""
            if desc_el is not None and desc_el.text:
                summary = _clean(desc_el.text)[:200]

            pub_date = ""
            if pub_el is not None and pub_el.text:
                pub_date = pub_el.text[:25]

            if title and len(title) > 5:
                real_source = _extract_source(link) if link else source_name
                items.append({
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "source": real_source,
                    "category": category,
                    "pub_date": pub_date,
                    "intl": True,
                })
    except Exception as e:
        print(f"    RSS error [{source_name}]: {e}")
    return items


def fetch_all_intl_rss():
    """抓取所有国际RSS源"""
    all_items = []
    print("  === 国际新闻RSS ===")
    for category, feeds in INTL_RSS_FEEDS.items():
        cat_count = 0
        for feed_url, source_name in feeds:
            items = fetch_rss_feed(feed_url, source_name, category, limit=8)
            if items:
                all_items.extend(items)
                cat_count += len(items)
                print(f"    {source_name}: {len(items)}条")
            time.sleep(0.3)
        print(f"  [{category}] RSS合计: {cat_count}条")
    return all_items


# ──────────────────── 同花顺快讯(备用) ────────────────────

def fetch_ths_global():
    items = []
    for page in range(1, 4):
        params = {"page": page, "tag": "", "track": "website", "pagesize": 30}
        r = _get(THS_NEWS_URL)
        if not r:
            continue
        try:
            data = r.json()
            for n in data.get("data", {}).get("list", []):
                title = n.get("title", "") or n.get("digest", "")
                if not title:
                    continue
                ctime = int(n.get("ctime", 0))
                items.append({
                    "title": title,
                    "link": n.get("url", ""),
                    "summary": (n.get("digest", "") or title)[:200],
                    "source": "同花顺",
                    "category": _auto_categorize(title),
                    "pub_date": datetime.fromtimestamp(ctime, BJT).strftime(
                        "%Y-%m-%d %H:%M") if ctime else "",
                })
        except Exception:
            pass
    return items


def _auto_categorize(text):
    t = text.lower()
    cat_kw = {
        "金融财经": ['股', '基金', '债', '利率', '央行', '银行', '美联储', '通胀',
                      'CPI', 'GDP', '黄金', '原油', '美元', '汇率', '期货',
                      'stock', 'market', 'fed', 'rate', 'gold', 'oil', 'bank',
                      'inflation', 'bond', 'nasdaq', 's&p', 'dow', 'bitcoin',
                      'crypto', 'earnings', 'wall street', 'finance'],
        "人工智能": ['AI', '人工智能', '大模型', 'GPT', '算力', '芯片', '机器人',
                      '自动驾驶', 'OpenAI', '英伟达',
                      'artificial intelligence', 'machine learning', 'chatgpt',
                      'nvidia', 'openai', 'deepmind', 'llm', 'neural'],
        "国际政治": ['总统', '外交', '选举', '制裁', '峰会', '联合国', '条约',
                      '谈判', '白宫', '国会',
                      'president', 'election', 'diplomat', 'sanction', 'summit',
                      'congress', 'parliament', 'nato', 'treaty', 'geopolit'],
        "军事安全": ['军事', '导弹', '航母', '战争', '冲突', '军队', '武器',
                      '演习', '国防', '核', '停火', '伊朗', '以色列',
                      'military', 'missile', 'war', 'conflict', 'army', 'navy',
                      'defense', 'weapon', 'nuclear', 'ceasefire', 'troops'],
        "科技前沿": ['quantum', 'space', 'rocket', 'satellite', 'robot',
                      'breakthrough', 'fusion', '量子', '航天', '火箭'],
    }
    for cat, keywords in cat_kw.items():
        if any(kw.lower() in t for kw in keywords):
            return cat
    return "综合资讯"


# ──────────────────── 英文标题翻译 ────────────────────

def _is_english(text):
    """判断文本是否主要为英文"""
    if not text:
        return False
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    return ascii_chars / max(len(text), 1) > 0.7


def _translate_google(text, src='en', tgt='zh-CN'):
    """通过 Google Translate 免费接口翻译"""
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx", "sl": src, "tl": tgt,
            "dt": "t", "q": text,
        }
        r = requests.get(url, params=params, timeout=8,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            data = r.json()
            # 返回格式: [[["翻译结果","原文",null,null,10]],null,"en"]
            if data and data[0]:
                return "".join(seg[0] for seg in data[0] if seg[0])
    except Exception as e:
        print(f"    翻译失败: {e}")
    return ""


def translate_items(items):
    """为英文标题添加中文翻译"""
    count = 0
    for item in items:
        title = item.get("title", "")
        if _is_english(title) and not item.get("title_cn"):
            cn = _translate_google(title)
            if cn and cn != title:
                item["title_cn"] = cn
                count += 1
            time.sleep(0.2)  # 避免请求过快
    print(f"  翻译英文标题: {count} 条")
    return items


# ──────────────────── 重要性评分 & 去重 ────────────────────

def score_importance(item):
    text = item["title"] + " " + item.get("summary", "")
    score = 0
    for weight, keywords in IMPORTANCE_KW.items():
        for kw in keywords:
            if kw.lower() in text.lower():
                score += weight
    # 权威媒体加分
    premium_cn = ['财联社', '华尔街见闻', '财新', '澎湃', '东方财富', '第一财经']
    premium_intl = ['Reuters', 'BBC', 'NYT', 'Bloomberg', 'CNBC', 'CNN',
                    'FT', 'WSJ', 'AP', 'Guardian', 'Al Jazeera',
                    'Foreign Affairs', 'Economist']
    src = item.get("source", "")
    if any(s in src for s in premium_intl):
        score += 3  # 国际权威媒体加分更多
    elif any(s in src for s in premium_cn):
        score += 2
    return score


def deduplicate(items):
    seen = []
    result = []
    for item in items:
        key = re.sub(r'\s+', '', item["title"])[:20]
        if key not in seen and len(item["title"]) > 5:
            seen.append(key)
            result.append(item)
    return result


# ──────────────────── 主流程 ────────────────────

def collect_all_news():
    """多源采集新闻: 国际RSS + Firecrawl/搜狗 + 同花顺"""
    all_items = []

    # 1. 国际RSS源 (主力)
    rss_items = fetch_all_intl_rss()
    all_items.extend(rss_items)
    print(f"  RSS总计: {len(rss_items)} 条")

    # 2. Firecrawl 中英文搜索
    print("  === Firecrawl 新闻搜索 ===")
    for category, queries in SEARCH_QUERIES.items():
        for q in queries:
            print(f"  搜索 [{category}] {q[:25]}...")
            items = search_firecrawl(q, category, limit=5)
            if not items:
                items = search_via_requests(q, category, limit=5)
            if items:
                all_items.extend(items)
                print(f"    → {len(items)} 条")
            else:
                print(f"    → 0 条")
            time.sleep(0.5)

    # 3. 补充同花顺快讯
    print("  === 同花顺快讯 ===")
    ths = fetch_ths_global()
    all_items.extend(ths)
    print(f"    → {len(ths)} 条")

    print(f"  共采集 {len(all_items)} 条原始新闻")
    return all_items


def build_digest(max_per_cat=8, total_max=40):
    now = datetime.now(BJT)
    print(f"\n{'='*50}")
    print(f"  全球资讯聚合 | {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    all_items = collect_all_news()
    all_items = deduplicate(all_items)
    print(f"  去重后: {len(all_items)} 条")

    for item in all_items:
        item["importance"] = score_importance(item)

    by_cat = defaultdict(list)
    for item in all_items:
        by_cat[item["category"]].append(item)

    digest = {}
    cat_order = ["金融财经", "人工智能", "国际政治", "军事安全", "科技前沿", "综合资讯"]
    total_count = 0
    for cat in cat_order:
        if cat in by_cat:
            sorted_items = sorted(by_cat[cat], key=lambda x: x["importance"], reverse=True)
            digest[cat] = sorted_items[:max_per_cat]
            total_count += len(digest[cat])
            print(f"  [{cat}] {len(by_cat[cat])}条 → 精选 {len(digest[cat])}条")

    # 翻译英文标题
    print("  === 翻译英文标题 ===")
    all_selected = []
    for items in digest.values():
        all_selected.extend(items)
    translate_items(all_selected)

    print(f"  最终摘要: {total_count} 条")
    return digest


# ──────────────────── 飞书推送 ────────────────────

CAT_EMOJI = {
    "金融财经": "💰", "人工智能": "🤖", "国际政治": "🌍",
    "军事安全": "🛡", "科技前沿": "🔬", "综合资讯": "📌",
}

def push_digest_feishu(digest, webhook=None):
    wh = webhook or FEISHU_WEBHOOK
    if not wh:
        print("  [SKIP] 飞书未配置")
        return False

    now = datetime.now(BJT)
    elements = []

    elements.append({
        "tag": "markdown",
        "content": f"**{now.strftime('%Y年%m月%d日')} 全球资讯早报**\n按重要性排序 | 金融·AI·政治·军事·科技"
    })
    elements.append({"tag": "hr"})

    cat_order = ["金融财经", "人工智能", "国际政治", "军事安全", "科技前沿", "综合资讯"]
    for cat in cat_order:
        items = digest.get(cat, [])
        if not items:
            continue

        emoji = CAT_EMOJI.get(cat, "📰")
        lines = [f"**{emoji} {cat}**\n"]

        for i, item in enumerate(items):
            title = item["title"][:60]
            title_cn = item.get("title_cn", "")
            source = item.get("source", "")
            link = item.get("link", "")
            summary = item.get("summary", "")

            imp = item.get("importance", 0)
            if imp >= 8:
                tag = "🔴"
            elif imp >= 5:
                tag = "🟡"
            else:
                tag = "⚪"

            # 显示标题（英文附带中文翻译）
            if link:
                line = f"{tag} **{i+1}. [{title}]({link})**"
            else:
                line = f"{tag} **{i+1}. {title}**"

            # 英文标题下面附上中文翻译
            if title_cn:
                line += f"\n　　📝 {title_cn}"

            if summary and summary != title and not title_cn:
                short = summary[:80]
                if len(summary) > 80:
                    short += "..."
                line += f"\n　　{short}"

            line += f"\n　　*— {source}*"
            lines.append(line)

        elements.append({
            "tag": "markdown",
            "content": "\n".join(lines)
        })
        elements.append({"tag": "hr"})

    elements.append({
        "tag": "markdown",
        "content": f"🔴极高重要性 🟡高重要性 ⚪一般\n生成于 {now.strftime('%H:%M')} 北京时间"
    })

    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text",
                          "content": f"📰 全球资讯早报 | {now.strftime('%m月%d日')}"},
                "template": "blue",
            },
            "elements": elements,
        }
    }

    try:
        r = requests.post(wh, json=card, timeout=15)
        resp = r.json()
        ok = resp.get("code", -1) == 0 or resp.get("StatusCode", -1) == 0
        print(f"  飞书推送: {'成功' if ok else '失败 ' + str(resp)}")
        return ok
    except Exception as e:
        print(f"  飞书推送异常: {e}")
        return False


# ──────────────────── 入口 ────────────────────

def run(webhook=None):
    digest = build_digest(max_per_cat=8, total_max=40)
    push_digest_feishu(digest, webhook)
    return digest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="全球资讯聚合推送")
    parser.add_argument("--webhook", help="飞书Webhook地址")
    args = parser.parse_args()
    wh = args.webhook or FEISHU_WEBHOOK
    run(wh)
