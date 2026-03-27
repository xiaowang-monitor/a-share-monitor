#!/usr/bin/env python3
"""
全球热门资讯聚合 + 飞书每日推送
覆盖: 金融、人工智能、政治、军事、科技、经济
数据源: Firecrawl 新闻搜索 + 同花顺7x24
"""

import os, json, re, time, subprocess, sys
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import requests

BJT = timezone(timedelta(hours=8))
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")

# ──────────────────── 搜索查询配置 ────────────────────

SEARCH_QUERIES = {
    "金融财经": [
        "全球金融市场 股市 美股 A股 今日",
        "央行 利率 汇率 黄金 原油 最新",
    ],
    "人工智能": [
        "人工智能 AI 大模型 最新进展",
        "AI芯片 算力 科技公司 突破",
    ],
    "国际政治": [
        "国际政治 外交 峰会 谈判 最新",
        "中美关系 欧盟 全球治理",
    ],
    "军事安全": [
        "军事冲突 战争 地缘政治 安全",
        "国防 武器 演习 军事部署",
    ],
    "科技前沿": [
        "科技突破 量子计算 航天 新技术 2026",
    ],
}

# 同花顺7x24
THS_NEWS_URL = "https://news.10jqka.com.cn/tapp/news/push/stock/"

# 重要性关键词权重
IMPORTANCE_KW = {
    5: ['突发', '重大', '紧急', '央行', '美联储', 'Fed', '降息', '加息',
        '战争', '冲突', '制裁', '禁令', '崩盘', '熔断', '黑天鹅',
        'GPT-5', 'AGI', '核武', '导弹', '入侵', '政变', '停火'],
    3: ['利好', '利空', '暴涨', '暴跌', '政策', '监管', '峰会',
        '总统', '主席', '首相', 'AI', '芯片', '半导体', '量子',
        '石油', '黄金', '美元', '人民币', 'GDP', 'CPI', '非农',
        '选举', '外交', '条约', '联合国', '北约', 'NATO',
        'OpenAI', 'Google', 'Apple', '微软', '英伟达', '特斯拉',
        '油价', '通胀', '衰退', '涨停', '跌停'],
    1: ['上涨', '下跌', '发布', '合作', '投资', '融资', '上市',
        '报告', '数据', '预测', '趋势', '创新', '突破', '机器人',
        '无人机', '卫星', '航母', '演习', '部署'],
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
        'wallstreetcn': '华尔街见闻', 'sina.com': '新浪', 'sohu.com': '搜狐',
        'eastmoney': '东方财富', 'caixin': '财新', 'bbc.com': 'BBC',
        'voachinese': 'VOA', 'nytimes': '纽约时报', 'storm.mg': '风传媒',
        'thepaper': '澎湃', 'guancha': '观察者网', '36kr': '36氪',
        'jfdaily': '解放日报', 'coindesk': 'CoinDesk', 'atvnews': 'ATV',
        'finance.sina': '新浪财经', 'cls.cn': '财联社',
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
    cat_kw = {
        "金融财经": ['股', '基金', '债', '利率', '央行', '银行', '美联储', '通胀',
                      'CPI', 'GDP', '黄金', '原油', '美元', '汇率', '期货'],
        "人工智能": ['AI', '人工智能', '大模型', 'GPT', '算力', '芯片', '机器人',
                      '自动驾驶', 'OpenAI', '英伟达'],
        "国际政治": ['总统', '外交', '选举', '制裁', '峰会', '联合国', '条约',
                      '谈判', '白宫', '国会'],
        "军事安全": ['军事', '导弹', '航母', '战争', '冲突', '军队', '武器',
                      '演习', '国防', '核', '停火', '伊朗', '以色列'],
    }
    for cat, keywords in cat_kw.items():
        if any(kw in text for kw in keywords):
            return cat
    return "综合资讯"


# ──────────────────── 重要性评分 & 去重 ────────────────────

def score_importance(item):
    text = item["title"] + " " + item.get("summary", "")
    score = 0
    for weight, keywords in IMPORTANCE_KW.items():
        for kw in keywords:
            if kw.lower() in text.lower():
                score += weight
    premium = ['财联社', '华尔街见闻', 'BBC', '财新', '澎湃', '纽约时报', '东方财富']
    if any(s in item.get("source", "") for s in premium):
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
    """多源采集新闻"""
    all_items = []
    print("  === Firecrawl 新闻搜索 ===")
    for category, queries in SEARCH_QUERIES.items():
        for q in queries:
            print(f"  搜索 [{category}] {q[:20]}...")
            items = search_firecrawl(q, category, limit=5)
            if not items:
                items = search_via_requests(q, category, limit=5)
            if items:
                all_items.extend(items)
                print(f"    → {len(items)} 条")
            else:
                print(f"    → 0 条")
            time.sleep(0.5)

    # 补充同花顺快讯
    print("  === 同花顺快讯 ===")
    ths = fetch_ths_global()
    all_items.extend(ths)
    print(f"    → {len(ths)} 条")

    print(f"  共采集 {len(all_items)} 条原始新闻")
    return all_items


def build_digest(max_per_cat=5, total_max=25):
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

            if link:
                line = f"{tag} **{i+1}. [{title}]({link})**"
            else:
                line = f"{tag} **{i+1}. {title}**"

            if summary and summary != title:
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
    digest = build_digest(max_per_cat=5, total_max=25)
    push_digest_feishu(digest, webhook)
    return digest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="全球资讯聚合推送")
    parser.add_argument("--webhook", help="飞书Webhook地址")
    args = parser.parse_args()
    wh = args.webhook or FEISHU_WEBHOOK
    run(wh)
