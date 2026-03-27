#!/usr/bin/env python3
"""
A股利好监控 + 短线量化交易系统
LIVE / BACKTEST / CALIBRATION 三模块统一架构
"""

import os, sys, json, re, time, math, hashlib, threading, signal
import random
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlencode, quote
import requests

# ──────────────────────── 时区 & 基础常量 ────────────────────────
BJT = timezone(timedelta(hours=8))

# 环境变量
TG_TOKEN    = os.getenv("TG_TOKEN", "")
TG_CHAT_ID  = os.getenv("TG_CHAT_ID", "")
TG_CHANNEL  = os.getenv("TG_CHANNEL", "")
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")

# A股 stockMarket 过滤
A_SHARE_MARKETS = {'22', '33', '151', '17'}

# 影响力等级阈值
IMPACT_LEVELS = {'S': 4.0, 'A': 2.5, 'B': 1.5}

# 重大新闻关键词
BREAKING_KW = [
    '重大', '突发', '紧急', '特大', '国务院', '央行', '证监会',
    '降准', '降息', '利好', '暴涨', '涨停', '历史性', '首次',
    '战略', '规划', '政策', '改革', '刺激', '救市',
]
OFFICIAL_KW = [
    '公告', '业绩预增', '业绩快报', '中标', '签约', '合同',
    '增持', '回购', '分红', '送转', '并购', '重组', '借壳',
]

# ──────────────────────── 板块映射 & 种子池 ────────────────────────
SECTOR_GROUPS = {
    '人工智能': ['AI', '算力', '大模型', '光模块', '液冷', '云计算', 'ChatGPT', 'GPU', '智算', '英伟达', '算力租赁'],
    '半导体':   ['芯片', '半导体', '光刻', 'EDA', '封测', '晶圆', 'ASML', '存储', 'HBM', 'DRAM'],
    '新能源':   ['锂电', '光伏', '风电', '储能', '新能源车', '充电桩', '氢能', '钠电池', '碳酸锂'],
    '医药':     ['创新药', '医药', 'CXO', '生物医药', '中药', '医疗器械', '疫苗', 'GLP-1', '减肥药'],
    '消费':     ['白酒', '消费', '食品', '家电', '免税', '旅游', '零售', '餐饮', '品牌'],
    '军工':     ['军工', '国防', '航天', '航空', '导弹', '卫星', '雷达', '无人机', '船舶'],
    '金融':     ['银行', '券商', '保险', '金融', '证券', '期货', '信托'],
    '地产':     ['房地产', '地产', '物业', '城投', '基建', '建材', '水泥'],
    '机器人':   ['机器人', '人形机器人', '减速器', '丝杠', '伺服', '特斯拉机器人', 'Optimus'],
    '数据要素': ['数据', '数据要素', '数据确权', '数据交易', '数字经济', '东数西算', '信创'],
    '低空经济': ['低空', 'eVTOL', '无人机', '飞行汽车', '空管', '通航'],
}

SECTOR_ETFS = {
    '人工智能': [('159819', '人工智能ETF'), ('515070', '人工智能ETF')],
    '半导体':   [('512480', '半导体ETF'), ('159995', '芯片ETF')],
    '新能源':   [('516160', '新能源ETF'), ('159875', '新能源车ETF')],
    '医药':     [('512010', '医药ETF'),   ('159992', '创新药ETF')],
    '消费':     [('159928', '消费ETF'),   ('512600', '主要消费ETF')],
    '军工':     [('512660', '军工ETF'),   ('512810', '军工龙头ETF')],
    '金融':     [('510230', '金融ETF'),   ('512880', '证券ETF')],
    '地产':     [('512200', '房地产ETF'), ('159707', '地产ETF')],
    '机器人':   [('562500', '机器人ETF'), ('159770', '机器人ETF')],
    '数据要素': [('516700', '数据ETF'),   ('159558', '数据要素ETF')],
    '低空经济': [('159857', '低空经济ETF')],
}

SEED_POOLS = {
    '人工智能': ['sz002230', 'sz300496', 'sh603019', 'sz300474', 'sh688256',
                 'sz002415', 'sh600588', 'sz300308', 'sz002049', 'sh688561'],
    '半导体':   ['sh688981', 'sz002371', 'sh688012', 'sh603501', 'sz300661',
                 'sz002185', 'sh688008', 'sz300223', 'sh688036', 'sz300782'],
    '新能源':   ['sz300750', 'sh601012', 'sz002594', 'sh600438', 'sz300274',
                 'sh601615', 'sz002709', 'sh688599', 'sz300014', 'sz300207'],
    '医药':     ['sh600276', 'sz300760', 'sz300347', 'sh603259', 'sz300122',
                 'sh688180', 'sz002821', 'sh600196', 'sz300759', 'sz000661'],
    '消费':     ['sh600519', 'sz000858', 'sh600887', 'sz000568', 'sh603369',
                 'sz002304', 'sh600809', 'sz000799', 'sh601888', 'sz002714'],
    '军工':     ['sh600893', 'sh601698', 'sz002179', 'sh600760', 'sz002414',
                 'sh600118', 'sh601989', 'sz000768', 'sh600150', 'sz002013'],
    '金融':     ['sh601318', 'sh600036', 'sh601688', 'sh600030', 'sh601166',
                 'sh601398', 'sh601939', 'sh601601', 'sh600000', 'sz000776'],
    '机器人':   ['sz300024', 'sh688007', 'sz002747', 'sh603728', 'sz300124',
                 'sz002527', 'sh603416', 'sz300503', 'sz002472', 'sh688165'],
}

# ──────────────────────── 交易参数 ────────────────────────
DEFAULT_PARAMS = {
    "buy_threshold": 70,
    "stop_loss_pct": 0.06,
    "take_profit_pct": 0.15,
    "w_sentiment": 25,
    "w_sector": 20,
    "w_leader": 20,
    "w_fund": 15,
    "w_vp": 10,
    "w_seal": 10,
    "price_max_live": 60,
    "mc_min_live": 50,
    "turn_min_live": 5,
    "price_max_bt": 200,
    "mc_min_bt": 0,
    "turn_min_bt": 3,
    "max_hold": 3,
    "hold_days_max": 5,
    "slippage": 0.002,
    "commission": 0.0003,
}

PARAMS_FILE = "trading_params.json"


def load_params():
    """加载交易参数"""
    if os.path.exists(PARAMS_FILE):
        try:
            with open(PARAMS_FILE, "r") as f:
                saved = json.load(f)
            merged = {**DEFAULT_PARAMS, **saved}
            return merged
        except Exception:
            pass
    return dict(DEFAULT_PARAMS)


def save_params(params):
    """保存交易参数"""
    with open(PARAMS_FILE, "w") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)


PARAMS = load_params()

# ──────────────────────── API 工具函数 ────────────────────────

def _get(url, params=None, timeout=10):
    """带重试的 GET 请求"""
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=timeout,
                             headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return r
        except Exception as e:
            if attempt == 2:
                print(f"[WARN] GET {url} failed: {e}")
                return None
            time.sleep(1)
    return None


def _stock_prefix(code):
    """股票代码加前缀: 6xx/688xx → sh, 0xx/3xx → sz"""
    code = code.strip()
    if code.startswith(('sh', 'sz')):
        return code
    if code.startswith(('6', '688')):
        return 'sh' + code
    if code.startswith(('0', '3')):
        return 'sz' + code
    return code


def is_market_hours():
    """判断是否在交易时段 (北京时间 9:15-15:05, 周一至周五)"""
    now = datetime.now(BJT)
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    return 915 <= t <= 1505


def now_bj():
    return datetime.now(BJT)

# ──────────────────────── 同花顺新闻 API ────────────────────────

THS_NEWS_URL = "https://news.10jqka.com.cn/tapp/news/push/stock/"

def fetch_ths_news(tag='', pages=4):
    """
    从同花顺7x24获取新闻
    tag: '' = 全部, '-21101' = 重要, '21109' = 机会
    """
    all_news = []
    seen_ids = set()
    for page in range(1, pages + 1):
        params = {
            "page": page,
            "tag": tag,
            "track": "website",
            "pagesize": 30,
        }
        r = _get(THS_NEWS_URL, params=params)
        if not r:
            continue
        try:
            data = r.json()
            items = data.get("data", {}).get("list", [])
        except Exception:
            continue
        for item in items:
            nid = str(item.get("id", ""))
            if nid in seen_ids:
                continue
            seen_ids.add(nid)
            # 过滤 A 股
            sm = str(item.get("stockMarket", ""))
            stock_code = item.get("stockCode", "")
            stock_name = item.get("stockName", "")
            title = item.get("title", "") or item.get("digest", "")
            ctime = item.get("ctime", 0)
            try:
                ctime = int(ctime)
            except (ValueError, TypeError):
                ctime = 0
            news_item = {
                "id": nid,
                "title": title,
                "content": item.get("digest", title),
                "ctime": ctime,
                "time_str": datetime.fromtimestamp(ctime, BJT).strftime("%H:%M:%S") if ctime else "",
                "stock_code": stock_code,
                "stock_name": stock_name,
                "stock_market": sm,
                "is_a_share": sm in A_SHARE_MARKETS,
                "source": item.get("source", ""),
                "url": item.get("url", ""),
            }
            all_news.append(news_item)
    all_news.sort(key=lambda x: x["ctime"], reverse=True)
    return all_news


def fetch_all_channels(pages=4):
    """从3个频道获取新闻并去重"""
    channels = ['', '-21101', '21109']
    merged = {}
    for tag in channels:
        items = fetch_ths_news(tag=tag, pages=pages)
        for item in items:
            if item["id"] not in merged:
                merged[item["id"]] = item
    result = sorted(merged.values(), key=lambda x: x["ctime"], reverse=True)
    return result


# ──────────────────────── 腾讯行情 API ────────────────────────

def fetch_tencent_quotes(symbols):
    """批量获取腾讯实时行情 (最多30个一批)"""
    if not symbols:
        return {}
    quotes = {}
    batches = [symbols[i:i+30] for i in range(0, len(symbols), 30)]
    for batch in batches:
        sym_str = ",".join(batch)
        url = f"https://qt.gtimg.cn/q={sym_str}"
        r = _get(url)
        if not r:
            continue
        text = r.text
        for line in text.strip().split(";"):
            line = line.strip()
            if not line or '=' not in line:
                continue
            parts = line.split("=")
            if len(parts) < 2:
                continue
            raw = parts[1].strip('"').strip()
            fields = raw.split("~")
            if len(fields) < 50:
                continue
            code = fields[2]
            prefix = 'sh' if fields[0] == '1' else 'sz'
            sym = prefix + code
            try:
                price = float(fields[3]) if fields[3] else 0
                prev_close = float(fields[4]) if fields[4] else 0
                pct = float(fields[32]) if fields[32] else 0
                volume = float(fields[6]) if fields[6] else 0
                amount = float(fields[37]) if fields[37] else 0
                high = float(fields[33]) if fields[33] else 0
                low = float(fields[34]) if fields[34] else 0
                open_ = float(fields[5]) if fields[5] else 0
                turnover = float(fields[38]) if fields[38] else 0
                pe_dyn = float(fields[39]) if fields[39] else 0
                market_cap = float(fields[45]) if fields[45] else 0
                vol_ratio = float(fields[49]) if fields[49] else 0
                pe_ttm = float(fields[52]) if len(fields) > 52 and fields[52] else 0
            except (ValueError, IndexError):
                continue
            quotes[sym] = {
                "symbol": sym,
                "name": fields[1],
                "price": price,
                "prev_close": prev_close,
                "pct": pct,
                "volume": volume,
                "amount": amount,
                "high": high,
                "low": low,
                "open": open_,
                "turnover": turnover,
                "pe_dyn": pe_dyn,
                "market_cap": market_cap,  # 亿
                "vol_ratio": vol_ratio,
                "pe_ttm": pe_ttm,
            }
    return quotes


def fetch_tencent_kline(symbol, days=60):
    """获取腾讯日K线数据"""
    code = symbol.replace("sh", "").replace("sz", "")
    market = 1 if symbol.startswith("sh") else 0
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    end_date = now_bj().strftime("%Y-%m-%d")
    params = {
        "param": f"{market == 1 and 'sh' or 'sz'}{code},day,,,{days},qfq",
        "_var": f"kline_dayqfq{code}",
    }
    # 使用更可靠的 URL 格式
    prefix = "sh" if market == 1 else "sz"
    full_url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,{days},qfq"
    r = _get(full_url)
    if not r:
        return []
    try:
        text = r.text
        # 去掉 callback wrapper
        if "=" in text:
            text = text.split("=", 1)[1]
        data = json.loads(text)
        stock_data = data.get("data", {}).get(f"{prefix}{code}", {})
        klines = stock_data.get("qfqday", stock_data.get("day", []))
        result = []
        for k in klines:
            if len(k) >= 6:
                result.append({
                    "date": k[0],
                    "open": float(k[1]),
                    "close": float(k[2]),
                    "high": float(k[3]),
                    "low": float(k[4]),
                    "volume": float(k[5]) if len(k) > 5 else 0,
                })
        return result
    except Exception as e:
        print(f"[WARN] K-line parse error for {symbol}: {e}")
        return []


# ──────────────────────── 情绪 & 板块分析 ────────────────────────

BULLISH_KW = [
    '利好', '大涨', '暴涨', '涨停', '突破', '新高', '放量', '大单',
    '增持', '回购', '分红', '业绩预增', '超预期', '翻倍', '爆发',
    '井喷', '强势', '龙头', '主力', '抄底', '机会', '布局', '低估',
    '景气', '高增长', '加速', '催化', '政策支持', '国产替代',
]
BEARISH_KW = [
    '利空', '大跌', '暴跌', '跌停', '破位', '新低', '缩量', '减持',
    '商誉', '亏损', '退市', '违规', '处罚', '爆雷', '暴雷', '下调',
    '警告', '风险', '压力', '回调', '套牢', '割肉', '恐慌', '崩盘',
]


def analyze_sentiment(news_list):
    """分析新闻情绪, 返回 0-100 分"""
    if not news_list:
        return 50
    bullish = 0
    bearish = 0
    total = len(news_list)
    for n in news_list:
        text = n.get("title", "") + n.get("content", "")
        b_count = sum(1 for kw in BULLISH_KW if kw in text)
        s_count = sum(1 for kw in BEARISH_KW if kw in text)
        if b_count > s_count:
            bullish += 1
        elif s_count > b_count:
            bearish += 1
    if total == 0:
        return 50
    ratio = (bullish - bearish) / total  # -1 ~ +1
    score = 50 + ratio * 50  # 0 ~ 100
    return max(0, min(100, score))


def extract_sectors(news_list):
    """从新闻中提取相关板块"""
    sector_hits = Counter()
    for n in news_list:
        text = n.get("title", "") + n.get("content", "")
        for sector, keywords in SECTOR_GROUPS.items():
            for kw in keywords:
                if kw in text:
                    sector_hits[sector] += 1
                    break
    return sector_hits.most_common()


def extract_stocks_from_news(news_list):
    """从新闻中提取个股 (通过API字段 + 正则匹配)"""
    stocks = {}
    # 股票代码正则: 6位数字
    code_pattern = re.compile(r'[（(](\d{6})[)）]')
    # 也匹配 "XXX(SH600519)" 格式
    code_pattern2 = re.compile(r'[（(]?(?:SH|SZ|sh|sz)(\d{6})[)）]?')

    for n in news_list:
        title = n.get("title", "")
        content = n.get("content", "")
        text = title + " " + content

        # 从 API 字段提取
        code = n.get("stock_code", "")
        name = n.get("stock_name", "")
        if code and n.get("is_a_share"):
            sym = _stock_prefix(code)
            if sym not in stocks:
                stocks[sym] = {"symbol": sym, "name": name, "mentions": 0, "news": []}
            stocks[sym]["mentions"] += 1
            stocks[sym]["news"].append(title)
            continue

        # 正则提取
        for pattern in [code_pattern, code_pattern2]:
            for match in pattern.finditer(text):
                raw_code = match.group(1)
                if raw_code.startswith(('6', '0', '3')):
                    sym = _stock_prefix(raw_code)
                    if sym not in stocks:
                        stocks[sym] = {"symbol": sym, "name": "", "mentions": 0, "news": []}
                    stocks[sym]["mentions"] += 1
                    stocks[sym]["news"].append(title)
    return stocks


# ──────────────────────── 一致性评分模型 ────────────────────────

def compute_score(sentiment_val, sector_val, leader_val, fund_val, vp_val, seal_val, params=None):
    """
    一致性评分模型 (满分100)
    sentiment_val, sector_val, ... 各维度原始值 0~100
    """
    p = params or PARAMS
    total = (
        sentiment_val * p["w_sentiment"] / 100 * (p["w_sentiment"] / 25) +
        sector_val   * p["w_sector"]    / 100 * (p["w_sector"]    / 20) +
        leader_val   * p["w_leader"]    / 100 * (p["w_leader"]    / 20) +
        fund_val     * p["w_fund"]      / 100 * (p["w_fund"]      / 15) +
        vp_val       * p["w_vp"]        / 100 * (p["w_vp"]        / 10) +
        seal_val     * p["w_seal"]      / 100 * (p["w_seal"]      / 10)
    )
    # 归一化: 权重之和等于各 w 参数之和
    w_sum = p["w_sentiment"] + p["w_sector"] + p["w_leader"] + p["w_fund"] + p["w_vp"] + p["w_seal"]
    if w_sum == 0:
        return 0
    # 简化: 直接按权重加权
    total = (
        sentiment_val * p["w_sentiment"] +
        sector_val   * p["w_sector"]    +
        leader_val   * p["w_leader"]    +
        fund_val     * p["w_fund"]      +
        vp_val       * p["w_vp"]        +
        seal_val     * p["w_seal"]
    ) / w_sum
    return round(min(100, max(0, total)), 1)


def score_sentiment(news_list, mode="LIVE"):
    """情绪维度评分 (0~100)"""
    return analyze_sentiment(news_list)


def score_sector(sector_hits, sector_name, mode="LIVE"):
    """板块维度评分: 板块热度排名映射到分数"""
    if not sector_hits:
        return 30
    ranked = [s for s, _ in sector_hits]
    if sector_name in ranked:
        idx = ranked.index(sector_name)
        total = len(ranked)
        return max(20, 100 - idx * (80 / max(total - 1, 1)))
    return 20


def score_leader_live(quote):
    """龙头维度评分 (实盘): 基于涨幅和量比"""
    pct = quote.get("pct", 0)
    vr = quote.get("vol_ratio", 1)
    score = 30
    if pct >= 9.5:    score += 50  # 涨停
    elif pct >= 5:    score += 35
    elif pct >= 2:    score += 20
    elif pct >= 0:    score += 10
    if vr >= 3:       score += 20
    elif vr >= 2:     score += 10
    elif vr >= 1.5:   score += 5
    return min(100, score)


def score_leader_bt(pct):
    """龙头维度评分 (回测): 日线涨幅阈值更低"""
    score = 35
    if pct >= 9:       score += 50
    elif pct >= 5:     score += 40
    elif pct >= 2:     score += 30
    elif pct >= 0.5:   score += 20
    elif pct >= 0:     score += 10
    elif pct >= -1:    score += 5
    return min(100, score)


def score_fund_live(quote):
    """资金维度评分 (实盘)"""
    score = 30
    vr = quote.get("vol_ratio", 1)
    turnover = quote.get("turnover", 0)
    if vr >= 3 and turnover >= 10:
        score += 40
    elif vr >= 2 and turnover >= 5:
        score += 25
    elif vr >= 1.5:
        score += 15
    amount = quote.get("amount", 0)
    if amount >= 10e8:    score += 30
    elif amount >= 5e8:   score += 20
    elif amount >= 1e8:   score += 10
    return min(100, score)


def score_fund_bt(kline_window):
    """资金维度评分 (回测): 基于K线量能"""
    if not kline_window or len(kline_window) < 2:
        return 45
    score = 35
    # 阳线占比
    up_days = sum(1 for k in kline_window if k["close"] > k["open"])
    ratio = up_days / len(kline_window)
    if ratio >= 0.7:    score += 30
    elif ratio >= 0.6:  score += 20
    elif ratio >= 0.5:  score += 10
    # 量能放大
    vols = [k["volume"] for k in kline_window]
    if len(vols) >= 5:
        recent_avg = sum(vols[-3:]) / 3
        old_avg = sum(vols[:-3]) / max(len(vols) - 3, 1)
        if old_avg > 0 and recent_avg / old_avg >= 2.0:
            score += 25
        elif old_avg > 0 and recent_avg / old_avg >= 1.5:
            score += 20
        elif old_avg > 0 and recent_avg / old_avg >= 1.2:
            score += 12
    # MA5 > MA10 趋势
    if len(kline_window) >= 10:
        ma5 = sum(k["close"] for k in kline_window[-5:]) / 5
        ma10 = sum(k["close"] for k in kline_window[-10:]) / 10
        if ma5 > ma10 * 1.02:
            score += 15
        elif ma5 > ma10:
            score += 8
    return min(100, score)


def score_vp_live(quote):
    """量价维度评分 (实盘)"""
    score = 30
    pct = quote.get("pct", 0)
    vr = quote.get("vol_ratio", 1)
    # 量价齐升
    if pct > 0 and vr >= 1.5:
        score += 30
    elif pct > 0 and vr >= 1:
        score += 15
    # 振幅
    high = quote.get("high", 0)
    low = quote.get("low", 0)
    prev = quote.get("prev_close", 0)
    if prev > 0:
        amp = (high - low) / prev * 100
        if 3 <= amp <= 8:
            score += 20
        elif amp < 3:
            score += 10
    return min(100, score)


def score_vp_bt(kline_window):
    """量价维度评分 (回测)"""
    if not kline_window or len(kline_window) < 3:
        return 45
    score = 35
    last = kline_window[-1]
    # 近3日连涨
    recent = kline_window[-3:]
    ups = sum(1 for k in recent if k["close"] > k["open"])
    if ups == 3:     score += 30
    elif ups >= 2:   score += 18
    elif ups >= 1:   score += 8
    # 量能配合
    vols = [k["volume"] for k in kline_window]
    if len(vols) >= 3 and vols[-1] > vols[-2] > vols[-3]:
        score += 20
    elif len(vols) >= 2 and vols[-1] > vols[-2]:
        score += 10
    # 收盘在上半区
    if last["high"] > last["low"]:
        pos = (last["close"] - last["low"]) / (last["high"] - last["low"])
        if pos >= 0.7:
            score += 10
    return min(100, score)


def score_seal_live(quote):
    """封单维度评分 (实盘): 涨停封单强度"""
    pct = quote.get("pct", 0)
    score = 20
    if pct >= 9.8:
        score += 60  # 涨停封板
        vr = quote.get("vol_ratio", 1)
        if vr >= 3:
            score += 20
    elif pct >= 7:
        score += 20
    return min(100, score)


def score_seal_bt(kline_day):
    """封单维度评分 (回测): close_strength 代理"""
    if not kline_day:
        return 30
    high = kline_day.get("high", 0)
    low = kline_day.get("low", 0)
    close = kline_day.get("close", 0)
    if high == low:
        return 85 if close > kline_day.get("open", 0) else 25
    strength = (close - low) / (high - low)
    score = 25 + strength * 55
    # 涨幅接近涨停
    open_ = kline_day.get("open", close)
    if open_ > 0:
        pct = (close - open_) / open_ * 100
        if pct >= 9:
            score += 25
        elif pct >= 5:
            score += 15
        elif pct >= 2:
            score += 8
    return min(100, score)


# ──────────────────────── 状态机 ────────────────────────

class TradingStateMachine:
    """
    状态机: IDLE → OBSERVE → READY → HOLD → EXIT → IDLE
    """
    STATES = ['IDLE', 'OBSERVE', 'READY', 'HOLD', 'EXIT']

    def __init__(self, symbol, name=""):
        self.symbol = symbol
        self.name = name
        self.state = 'IDLE'
        self.score = 0
        self.entry_price = 0
        self.entry_date = ""
        self.hold_days = 0
        self.highest_price = 0
        self.scores_history = []

    def update(self, score, price, date_str, params=None):
        """更新状态机, 返回操作信号"""
        p = params or PARAMS
        self.score = score
        self.scores_history.append(score)
        signal = None

        if self.state == 'IDLE':
            if score >= 65:
                self.state = 'OBSERVE'
                signal = 'OBSERVE'

        elif self.state == 'OBSERVE':
            if score >= p["buy_threshold"]:
                self.state = 'READY'
                signal = 'READY'
            elif score < 55:
                self.state = 'IDLE'
                signal = 'CANCEL'

        elif self.state == 'READY':
            # 由外部调用 enter_hold() 确认买入
            if score < 58:
                self.state = 'IDLE'
                signal = 'CANCEL'

        elif self.state == 'HOLD':
            self.hold_days += 1
            if price > self.highest_price:
                self.highest_price = price
            # 止损
            if self.entry_price > 0:
                loss = (price - self.entry_price) / self.entry_price
                if loss <= -p["stop_loss_pct"]:
                    self.state = 'EXIT'
                    signal = 'STOP_LOSS'
                    return signal
            # 止盈
            if self.entry_price > 0:
                gain = (price - self.entry_price) / self.entry_price
                if gain >= p["take_profit_pct"]:
                    self.state = 'EXIT'
                    signal = 'TAKE_PROFIT'
                    return signal
            # 回撤止盈
            if self.highest_price > 0 and self.entry_price > 0:
                from_high = (price - self.highest_price) / self.highest_price
                gain = (self.highest_price - self.entry_price) / self.entry_price
                if gain >= 0.08 and from_high <= -0.03:
                    self.state = 'EXIT'
                    signal = 'TRAIL_STOP'
                    return signal
            # 持仓天数限制
            if self.hold_days >= p["hold_days_max"]:
                self.state = 'EXIT'
                signal = 'TIME_EXIT'
                return signal
            # 评分衰退
            if score < 50:
                self.state = 'EXIT'
                signal = 'SCORE_EXIT'

        elif self.state == 'EXIT':
            self.state = 'IDLE'
            self.entry_price = 0
            self.hold_days = 0
            self.highest_price = 0
            signal = 'IDLE'

        return signal

    def enter_hold(self, price, date_str):
        """确认买入进入持仓状态"""
        self.state = 'HOLD'
        self.entry_price = price
        self.entry_date = date_str
        self.hold_days = 0
        self.highest_price = price

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "name": self.name,
            "state": self.state,
            "score": self.score,
            "entry_price": self.entry_price,
            "entry_date": self.entry_date,
            "hold_days": self.hold_days,
        }


# ──────────────────────── LIVE 模式 ────────────────────────

def _get_candidate_symbols(news_stocks, sector_hits):
    """获取候选股票列表 (新闻提取 + 种子池)"""
    symbols = set()
    # 从新闻提取
    for sym in news_stocks:
        symbols.add(sym)
    # 从热门板块的种子池 (取前5个板块)
    for sector, count in sector_hits[:5]:
        if sector in SEED_POOLS:
            for sym in SEED_POOLS[sector]:
                symbols.add(sym)
    # 若候选太少, 补充默认板块
    if len(symbols) < 20:
        for sec in ['人工智能', '半导体', '新能源']:
            if sec in SEED_POOLS:
                for sym in SEED_POOLS[sec]:
                    symbols.add(sym)
    return list(symbols)


def _filter_live(quote, params=None):
    """实盘过滤条件"""
    p = params or PARAMS
    if quote["price"] <= 0:
        return False
    if quote["price"] > p["price_max_live"]:
        return False
    if quote["market_cap"] > 0 and quote["market_cap"] < p["mc_min_live"]:
        return False
    # 非交易时段放宽换手率要求 (收盘后数据可能不完整)
    if is_market_hours():
        if quote["turnover"] < p["turn_min_live"]:
            return False
    else:
        if quote["turnover"] > 0 and quote["turnover"] < max(p["turn_min_live"] - 3, 0):
            return False
    return True


def _filter_bt(quote, params=None):
    """回测过滤条件 (放宽)"""
    p = params or PARAMS
    if quote.get("price", 0) <= 0:
        return False
    if quote.get("price", 0) > p["price_max_bt"]:
        return False
    return True


def compute_hot7(news_list, sector_hits):
    """计算 Hot7 热门排行: 结合新闻提及 + 板块热度"""
    stocks = extract_stocks_from_news(news_list)
    # 如果新闻提取太少, 用板块龙头补充
    if len(stocks) < 7:
        for sector, count in sector_hits[:3]:
            if sector in SEED_POOLS:
                for sym in SEED_POOLS[sector][:2]:
                    if sym not in stocks:
                        stocks[sym] = {
                            "symbol": sym, "name": f"{sector}概念",
                            "mentions": count, "news": [f"板块热度: {sector}"]
                        }
    ranked = sorted(stocks.values(), key=lambda x: x["mentions"], reverse=True)
    return ranked[:7]


def score_stock_live(symbol, quote, news_list, sector_hits, params=None):
    """实盘个股综合评分"""
    p = params or PARAMS
    # 判断所属板块
    stock_sector = ""
    name = quote.get("name", "")
    for sector, keywords in SECTOR_GROUPS.items():
        for kw in keywords:
            if kw in name:
                stock_sector = sector
                break
        if stock_sector:
            break

    sent_score = score_sentiment(news_list, "LIVE")
    sec_score = score_sector(sector_hits, stock_sector, "LIVE")
    leader_score = score_leader_live(quote)
    fund_score = score_fund_live(quote)
    vp_score = score_vp_live(quote)
    seal_score = score_seal_live(quote)

    total = compute_score(sent_score, sec_score, leader_score,
                          fund_score, vp_score, seal_score, p)
    return {
        "total": total,
        "sentiment": round(sent_score, 1),
        "sector": round(sec_score, 1),
        "leader": round(leader_score, 1),
        "fund": round(fund_score, 1),
        "vp": round(vp_score, 1),
        "seal": round(seal_score, 1),
        "sector_name": stock_sector,
    }


def _compute_consecutive_ups(klines):
    """计算连涨天数"""
    if not klines:
        return 0
    streak = 0
    for k in reversed(klines):
        if k["close"] > k["open"]:
            streak += 1
        else:
            break
    return streak


def run_pipeline(params=None):
    """
    主流水线: 获取新闻 → 分析 → 行情 → 评分 → 返回5个值
    Returns: hot7, rt_picks, quotes, all_news, sec_sum
    """
    p = params or PARAMS
    print(f"[{now_bj().strftime('%H:%M:%S')}] 开始数据刷新...")

    # 1. 获取新闻
    all_news = fetch_all_channels(pages=4)
    print(f"  获取新闻 {len(all_news)} 条")

    # 2. 分析
    sector_hits = extract_sectors(all_news)
    news_stocks = extract_stocks_from_news(all_news)
    hot7 = compute_hot7(all_news, sector_hits)

    # 3. 候选股票
    candidates = _get_candidate_symbols(news_stocks, sector_hits)
    print(f"  候选股票 {len(candidates)} 只")

    # 4. 行情
    quotes = fetch_tencent_quotes(candidates)
    print(f"  获取行情 {len(quotes)} 只")

    # 5. 个股评分 + 过滤
    rt_picks = []
    for sym, q in quotes.items():
        if not _filter_live(q, p):
            continue
        scores = score_stock_live(sym, q, all_news, sector_hits, p)
        # K线连涨
        klines = fetch_tencent_kline(sym, days=10)
        ups = _compute_consecutive_ups(klines)
        pick = {
            **q,
            **scores,
            "consecutive_ups": ups,
        }
        rt_picks.append(pick)

    rt_picks.sort(key=lambda x: x["total"], reverse=True)
    rt_picks = rt_picks[:20]

    # 6. 板块汇总
    sec_sum = []
    for sector, count in sector_hits[:8]:
        etfs = SECTOR_ETFS.get(sector, [])
        etf_syms = []
        for etf_code, etf_name in etfs:
            sym = _stock_prefix(etf_code)
            etf_syms.append(sym)
        etf_quotes = fetch_tencent_quotes(etf_syms) if etf_syms else {}
        sec_item = {
            "name": sector,
            "hit_count": count,
            "etfs": [],
        }
        for sym, eq in etf_quotes.items():
            sec_item["etfs"].append({
                "symbol": sym,
                "name": eq["name"],
                "pct": eq["pct"],
                "amount": eq["amount"],
            })
        sec_sum.append(sec_item)

    print(f"  评分完成, 精选 {len(rt_picks)} 只")
    return hot7, rt_picks, quotes, all_news, sec_sum


# ──────────────────────── BACKTEST 模式 ────────────────────────

def _kline_to_day_quote(kline, prev_kline=None):
    """将K线数据转换为日行情 quote 格式"""
    close = kline["close"]
    open_ = kline["open"]
    prev_close = prev_kline["close"] if prev_kline else open_
    pct = (close - prev_close) / prev_close * 100 if prev_close else 0
    return {
        "price": close,
        "open": open_,
        "close": close,
        "high": kline["high"],
        "low": kline["low"],
        "prev_close": prev_close,
        "pct": pct,
        "volume": kline.get("volume", 0),
        "amount": 0,
        "turnover": 6,  # 回测默认换手率
        "market_cap": 200,  # 回测默认市值(亿)
        "vol_ratio": 1.0,
        "name": "",
        "symbol": "",
    }


def _enrich_bt_quote(quote, kline_window):
    """用K线窗口丰富回测行情数据"""
    if len(kline_window) >= 5:
        vols = [k["volume"] for k in kline_window]
        avg_vol = sum(vols[:-1]) / max(len(vols) - 1, 1)
        cur_vol = vols[-1]
        if avg_vol > 0:
            quote["vol_ratio"] = round(cur_vol / avg_vol, 2)
            quote["turnover"] = round(quote["vol_ratio"] * 6, 1)
    return quote


def _bt_sentiment_proxy(pool_klines, date_idx):
    """回测情绪代理: 基于股票池涨跌比 + 近3日趋势"""
    ups = 0
    downs = 0
    limit_ups = 0
    strong_ups = 0  # 涨幅>2%
    for sym, klines in pool_klines.items():
        if date_idx >= len(klines):
            continue
        k = klines[date_idx]
        prev = klines[date_idx - 1] if date_idx > 0 else k
        pct = (k["close"] - prev["close"]) / prev["close"] * 100 if prev["close"] else 0
        if pct > 0:
            ups += 1
        elif pct < 0:
            downs += 1
        if pct >= 9.5:
            limit_ups += 1
        if pct >= 2:
            strong_ups += 1
    total = ups + downs
    if total == 0:
        return 55
    ratio = (ups - downs) / total  # -1 ~ +1
    # 基础分50, 涨跌比贡献±35, 强势股+15, 涨停+10
    score = 55 + ratio * 35 + min(strong_ups * 3, 15) + min(limit_ups * 5, 10)
    # 近3日趋势加成
    if date_idx >= 3:
        trend_ups = 0
        for d in range(date_idx - 2, date_idx + 1):
            day_up = 0
            day_total = 0
            for sym, klines in pool_klines.items():
                if d >= len(klines) or d < 1:
                    continue
                pct = (klines[d]["close"] - klines[d-1]["close"]) / klines[d-1]["close"] * 100
                if pct > 0:
                    day_up += 1
                day_total += 1
            if day_total > 0 and day_up / day_total > 0.5:
                trend_ups += 1
        if trend_ups == 3:
            score += 10
    return max(0, min(100, score))


def _bt_sector_score(etf_klines, date_idx):
    """回测板块评分: 基于ETF表现"""
    if not etf_klines:
        return 50
    scores = []
    for sym, klines in etf_klines.items():
        if date_idx >= len(klines) or date_idx < 1:
            continue
        k = klines[date_idx]
        prev = klines[date_idx - 1]
        pct = (k["close"] - prev["close"]) / prev["close"] * 100 if prev["close"] else 0
        if pct >= 3:
            scores.append(95)
        elif pct >= 2:
            scores.append(85)
        elif pct >= 1:
            scores.append(72)
        elif pct >= 0.3:
            scores.append(60)
        elif pct >= 0:
            scores.append(52)
        elif pct >= -1:
            scores.append(40)
        else:
            scores.append(25)
    return sum(scores) / len(scores) if scores else 50


def run_backtest(params=None, days=60, sectors=None):
    """
    回测模式: K线数据驱动
    返回: trades_list, stats_dict
    """
    p = params or PARAMS
    if sectors is None:
        sectors = list(SEED_POOLS.keys())[:3]

    print(f"\n{'='*60}")
    print(f"  回测模式 | 周期: {days}天 | 板块: {', '.join(sectors)}")
    print(f"  参数: buy={p['buy_threshold']}, sl={p['stop_loss_pct']}, tp={p['take_profit_pct']}")
    print(f"  权重: sent={p['w_sentiment']}, sec={p['w_sector']}, ldr={p['w_leader']}, "
          f"fund={p['w_fund']}, vp={p['w_vp']}, seal={p['w_seal']}")
    print(f"{'='*60}")

    # 收集候选股票
    all_syms = []
    for sec in sectors:
        if sec in SEED_POOLS:
            all_syms.extend(SEED_POOLS[sec])
    all_syms = list(set(all_syms))

    # 收集ETF
    etf_syms = []
    for sec in sectors:
        for code, name in SECTOR_ETFS.get(sec, []):
            etf_syms.append(_stock_prefix(code))

    # 获取K线
    print("  获取K线数据...")
    pool_klines = {}
    for sym in all_syms:
        klines = fetch_tencent_kline(sym, days=days + 20)
        if klines and len(klines) >= 20:
            pool_klines[sym] = klines

    etf_kline_data = {}
    for sym in etf_syms:
        klines = fetch_tencent_kline(sym, days=days + 20)
        if klines:
            etf_kline_data[sym] = klines

    print(f"  有效股票: {len(pool_klines)}, ETF: {len(etf_kline_data)}")

    if not pool_klines:
        print("  [ERROR] 无有效K线数据")
        return [], {}

    # 确定回测日期范围
    max_len = min(len(v) for v in pool_klines.values())
    start_idx = max(20, max_len - days)  # 留20天作为窗口

    # 模拟交易
    trades = []
    machines = {}
    capital = 1_000_000
    initial_capital = capital
    holdings = {}  # sym -> {shares, entry_price, entry_date}
    equity_curve = []
    max_equity = capital

    for idx in range(start_idx, max_len):
        # 计算情绪代理
        sent_score = _bt_sentiment_proxy(pool_klines, idx)
        sec_score = _bt_sector_score(etf_kline_data, idx)

        # 遍历每只股票
        for sym, klines in pool_klines.items():
            if idx >= len(klines):
                continue

            k = klines[idx]
            prev_k = klines[idx - 1] if idx > 0 else k
            date_str = k["date"]

            # 构建 quote
            quote = _kline_to_day_quote(k, prev_k)
            window = klines[max(0, idx - 10):idx + 1]
            quote = _enrich_bt_quote(quote, window)
            quote["symbol"] = sym

            if not _filter_bt(quote, p):
                continue

            # 各维度评分 (回测版)
            pct = quote["pct"]
            leader_s = score_leader_bt(pct)
            fund_s = score_fund_bt(window)
            vp_s = score_vp_bt(window)
            seal_s = score_seal_bt(k)

            total = compute_score(sent_score, sec_score, leader_s,
                                  fund_s, vp_s, seal_s, p)

            # 状态机
            if sym not in machines:
                machines[sym] = TradingStateMachine(sym)
            sm = machines[sym]
            signal = sm.update(total, k["close"], date_str, p)

            # 买入信号 (D日收盘信号, D+1日开盘执行)
            if sm.state == 'READY' and sym not in holdings:
                if len(holdings) < p["max_hold"] and idx + 1 < len(klines):
                    next_k = klines[idx + 1]
                    buy_price = next_k["open"] * (1 + p["slippage"])
                    cost = buy_price * 100  # 1手
                    fee = cost * p["commission"]
                    if capital >= cost + fee:
                        capital -= (cost + fee)
                        holdings[sym] = {
                            "shares": 100,
                            "entry_price": buy_price,
                            "entry_date": next_k["date"],
                            "score": total,
                        }
                        sm.enter_hold(buy_price, next_k["date"])

            # 卖出信号
            if signal in ('STOP_LOSS', 'TAKE_PROFIT', 'TRAIL_STOP',
                          'TIME_EXIT', 'SCORE_EXIT') and sym in holdings:
                if idx + 1 < len(klines):
                    next_k = klines[idx + 1]
                    sell_price = next_k["open"] * (1 - p["slippage"])
                else:
                    sell_price = k["close"] * (1 - p["slippage"])
                h = holdings[sym]
                revenue = sell_price * h["shares"]
                fee = revenue * p["commission"]
                capital += (revenue - fee)
                profit = (sell_price - h["entry_price"]) / h["entry_price"] * 100
                trades.append({
                    "symbol": sym,
                    "entry_date": h["entry_date"],
                    "entry_price": round(h["entry_price"], 2),
                    "exit_date": date_str,
                    "exit_price": round(sell_price, 2),
                    "profit_pct": round(profit, 2),
                    "signal": signal,
                    "score": h["score"],
                })
                del holdings[sym]

        # 记录权益
        hold_value = sum(
            pool_klines[s][min(idx, len(pool_klines[s]) - 1)]["close"] * h["shares"]
            for s, h in holdings.items()
            if s in pool_klines
        )
        equity = capital + hold_value
        equity_curve.append({"date": klines[idx]["date"] if klines else "", "equity": equity})
        max_equity = max(max_equity, equity)

    # 强制平仓
    for sym, h in list(holdings.items()):
        if sym in pool_klines and pool_klines[sym]:
            last_k = pool_klines[sym][-1]
            sell_price = last_k["close"] * (1 - p["slippage"])
            revenue = sell_price * h["shares"]
            capital += revenue * (1 - p["commission"])
            profit = (sell_price - h["entry_price"]) / h["entry_price"] * 100
            trades.append({
                "symbol": sym,
                "entry_date": h["entry_date"],
                "entry_price": round(h["entry_price"], 2),
                "exit_date": last_k["date"],
                "exit_price": round(sell_price, 2),
                "profit_pct": round(profit, 2),
                "signal": "FORCE_EXIT",
                "score": h["score"],
            })
    holdings.clear()

    # 统计
    total_equity = capital
    total_return = (total_equity - initial_capital) / initial_capital * 100
    win_trades = [t for t in trades if t["profit_pct"] > 0]
    win_rate = len(win_trades) / len(trades) * 100 if trades else 0
    avg_profit = sum(t["profit_pct"] for t in win_trades) / len(win_trades) if win_trades else 0
    loss_trades = [t for t in trades if t["profit_pct"] <= 0]
    avg_loss = sum(t["profit_pct"] for t in loss_trades) / len(loss_trades) if loss_trades else 0
    pl_ratio = abs(avg_profit / avg_loss) if avg_loss != 0 else 999

    max_dd = 0
    peak = initial_capital
    for e in equity_curve:
        if e["equity"] > peak:
            peak = e["equity"]
        dd = (peak - e["equity"]) / peak
        max_dd = max(max_dd, dd)

    annual_factor = 252 / max(days, 1)
    annual_return = total_return * annual_factor

    stats = {
        "total_return": round(total_return, 2),
        "annual_return": round(annual_return, 2),
        "trade_count": len(trades),
        "win_rate": round(win_rate, 1),
        "avg_profit": round(avg_profit, 2),
        "avg_loss": round(avg_loss, 2),
        "pl_ratio": round(pl_ratio, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "final_equity": round(total_equity, 0),
    }

    print(f"\n  回测结果:")
    print(f"  总收益: {stats['total_return']}% | 年化: {stats['annual_return']}%")
    print(f"  交易次数: {stats['trade_count']} | 胜率: {stats['win_rate']}%")
    print(f"  盈亏比: {stats['pl_ratio']} | 最大回撤: {stats['max_drawdown']}%")

    return trades, stats


# ──────────────────────── CALIBRATION 模式 ────────────────────────

def _eval_composite(stats):
    """评估函数: composite = annual_return*0.4 + win_rate*0.2 + PL_ratio*20*0.2 - max_drawdown*0.2"""
    ar = stats.get("annual_return", 0)
    wr = stats.get("win_rate", 0)
    pl = stats.get("pl_ratio", 0)
    dd = stats.get("max_drawdown", 0)
    return ar * 0.4 + wr * 0.2 + min(pl * 20, 100) * 0.2 - dd * 0.2


def run_calibration(days=60, sectors=None):
    """
    网格搜索标定: 搜索 (buy_threshold, stop_loss_pct, w_sentiment, w_leader) 的最优组合
    81种组合 (3^4)
    """
    print(f"\n{'='*60}")
    print(f"  参数标定模式 (CALIBRATION)")
    print(f"  回测周期: {days}天")
    print(f"{'='*60}")

    grid = {
        "buy_threshold": [70, 75, 80],
        "stop_loss_pct": [0.04, 0.06, 0.08],
        "w_sentiment":   [20, 25, 30],
        "w_leader":      [15, 20, 25],
    }

    combos = []
    for bt in grid["buy_threshold"]:
        for sl in grid["stop_loss_pct"]:
            for ws in grid["w_sentiment"]:
                for wl in grid["w_leader"]:
                    combos.append({
                        "buy_threshold": bt,
                        "stop_loss_pct": sl,
                        "w_sentiment": ws,
                        "w_leader": wl,
                    })

    print(f"  共 {len(combos)} 种参数组合")

    results = []
    for i, combo in enumerate(combos):
        test_params = {**PARAMS, **combo}
        # 调整其他权重保持总和=100
        remaining = 100 - test_params["w_sentiment"] - test_params["w_leader"]
        test_params["w_sector"] = 20
        test_params["w_fund"] = remaining - 30  # 扣除 sector(20) + vp(10)... 简化处理
        test_params["w_fund"] = max(10, min(20, test_params["w_fund"]))
        test_params["w_vp"] = 10
        test_params["w_seal"] = 100 - test_params["w_sentiment"] - test_params["w_sector"] - \
                                test_params["w_leader"] - test_params["w_fund"] - test_params["w_vp"]
        test_params["w_seal"] = max(5, test_params["w_seal"])

        trades, stats = run_backtest(test_params, days=days, sectors=sectors)
        score = _eval_composite(stats)

        results.append({
            "params": combo,
            "full_params": test_params,
            "stats": stats,
            "score": score,
        })

        if (i + 1) % 10 == 0:
            print(f"  进度: {i+1}/{len(combos)}")

    # 筛选满足约束的结果
    constrained = [r for r in results
                   if r["stats"].get("win_rate", 0) >= 55
                   and r["stats"].get("pl_ratio", 0) >= 1.5
                   and r["stats"].get("max_drawdown", 0) <= 15]

    if constrained:
        best = max(constrained, key=lambda x: x["score"])
        print(f"\n  [约束最优] score={best['score']:.1f}")
    else:
        best = max(results, key=lambda x: x["score"])
        print(f"\n  [无约束最优 (约束条件未满足)] score={best['score']:.1f}")

    print(f"  最优参数: {json.dumps(best['params'], indent=2)}")
    print(f"  回测统计: {json.dumps(best['stats'], indent=2)}")

    # 保存最优参数
    new_params = {**PARAMS, **best["full_params"]}
    save_params(new_params)
    print(f"  参数已保存至 {PARAMS_FILE}")

    return best


# ──────────────────────── 推送: 飞书 ────────────────────────

def push_feishu(title, content_lines, picks=None, agent_report=""):
    """飞书 Webhook 推送 (interactive card)"""
    if not FEISHU_WEBHOOK:
        print("  [SKIP] 飞书 webhook 未配置")
        return False

    # 构建卡片内容
    elements = []

    # 标题
    elements.append({
        "tag": "markdown",
        "content": f"**{title}**"
    })

    # 分隔线
    elements.append({"tag": "hr"})

    # 内容
    md_content = "\n".join(content_lines)
    elements.append({
        "tag": "markdown",
        "content": md_content
    })

    # 精选股票
    if picks:
        elements.append({"tag": "hr"})
        pick_lines = ["**精选个股 TOP5:**"]
        for i, p in enumerate(picks[:5]):
            sym = p.get("symbol", "")
            name = p.get("name", "")
            total = p.get("total", 0)
            pct = p.get("pct", 0)
            color = "red" if pct >= 0 else "green"
            pick_lines.append(
                f"{i+1}. **{name}**({sym}) 评分:{total} "
                f"涨幅:{pct:+.2f}%"
            )
        elements.append({
            "tag": "markdown",
            "content": "\n".join(pick_lines)
        })

    # 交易代理报告
    if agent_report:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "markdown",
            "content": f"**交易代理:**\n{agent_report}"
        })

    # 时间戳
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "markdown",
        "content": f"⏰ {now_bj().strftime('%Y-%m-%d %H:%M:%S')} (北京时间)"
    })

    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": "A股利好监控"},
                "template": "red",
            },
            "elements": elements,
        }
    }

    try:
        r = requests.post(FEISHU_WEBHOOK, json=card, timeout=10)
        resp = r.json()
        ok = resp.get("code", -1) == 0 or resp.get("StatusCode", -1) == 0
        if ok:
            print("  飞书推送成功")
        else:
            print(f"  飞书推送失败: {resp}")
        return ok
    except Exception as e:
        print(f"  飞书推送异常: {e}")
        return False


# ──────────────────────── 推送: Telegram ────────────────────────

def push_telegram(text):
    """Telegram Bot 推送"""
    if not TG_TOKEN or not TG_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.json().get("ok", False)
    except Exception:
        return False


# ──────────────────────── 重大新闻即时提醒 ────────────────────────

_alerted_ids = set()

def check_breaking_news(news_list):
    """检查重大新闻, 即时推送"""
    for n in news_list:
        nid = n["id"]
        if nid in _alerted_ids:
            continue
        title = n.get("title", "")
        content = n.get("content", "")
        text = title + content

        is_breaking = any(kw in text for kw in BREAKING_KW)
        is_official = any(kw in text for kw in OFFICIAL_KW)

        if not (is_breaking or is_official):
            continue

        # 计算影响力
        b_count = sum(1 for kw in BREAKING_KW if kw in text)
        o_count = sum(1 for kw in OFFICIAL_KW if kw in text)
        impact_score = b_count * 0.8 + o_count * 0.6

        if impact_score >= IMPACT_LEVELS['S']:
            level = 'S'
        elif impact_score >= IMPACT_LEVELS['A']:
            level = 'A'
        else:
            continue  # 只推送 S/A 级

        _alerted_ids.add(nid)
        stock_info = f"{n.get('stock_name', '')}({n.get('stock_code', '')})" if n.get('stock_code') else ""

        alert_lines = [
            f"**[{level}级重大利好]**",
            f"**{title}**",
            f"{stock_info}" if stock_info else "",
            f"来源: {n.get('source', '未知')}",
            f"时间: {n.get('time_str', '')}",
        ]

        push_feishu(f"{level}级重大利好提醒", [l for l in alert_lines if l])
        push_telegram(f"🚨 [{level}级重大利好]\n{title}\n{stock_info}")
        print(f"  [BREAKING] {level}级: {title}")


# ──────────────────────── HTML 面板模板 ────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股利好监控面板</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {
  --bg-primary: #0a0e17;
  --bg-card: #111827;
  --bg-card-hover: #1a2332;
  --border: #1e293b;
  --text-primary: #e2e8f0;
  --text-secondary: #94a3b8;
  --text-muted: #64748b;
  --red: #ef4444;
  --red-bg: rgba(239,68,68,0.1);
  --green: #22c55e;
  --green-bg: rgba(34,197,94,0.1);
  --gold: #f59e0b;
  --blue: #3b82f6;
  --purple: #8b5cf6;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family: 'Noto Sans SC', sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  min-height: 100vh;
}
.mono { font-family: 'JetBrains Mono', monospace; }
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
  transition: all 0.2s;
}
.card:hover { background: var(--bg-card-hover); border-color: #334155; }
.badge {
  display: inline-flex; align-items: center; padding: 2px 8px;
  border-radius: 6px; font-size: 12px; font-weight: 500;
}
.badge-s { background: rgba(239,68,68,0.2); color: #ef4444; }
.badge-a { background: rgba(245,158,11,0.2); color: #f59e0b; }
.badge-b { background: rgba(59,130,246,0.2); color: #3b82f6; }
.badge-c { background: rgba(100,116,139,0.2); color: #94a3b8; }
.score-bar {
  height: 6px; border-radius: 3px; background: #1e293b; overflow: hidden;
}
.score-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s; }
.up { color: var(--red); }
.down { color: var(--green); }
.pulse { animation: pulse 2s infinite; }
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.glow { box-shadow: 0 0 20px rgba(59,130,246,0.15); }
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
</style>
<script>
tailwind.config = {
  theme: { extend: { colors: {
    'brand': { 50:'#eff6ff', 500:'#3b82f6', 900:'#1e3a5f' }
  }}}
}
</script>
</head>
<body class="p-4 md:p-6 lg:p-8">

<!-- 顶部状态栏 -->
<div class="flex flex-wrap items-center justify-between mb-6 gap-4">
  <div class="flex items-center gap-3">
    <div class="w-10 h-10 bg-gradient-to-br from-red-500 to-orange-500 rounded-lg flex items-center justify-center font-bold text-white text-lg">A</div>
    <div>
      <h1 class="text-xl font-bold">A股利好监控面板</h1>
      <p class="text-xs text-gray-500">实盘监控 + 短线量化交易系统</p>
    </div>
  </div>
  <div class="flex items-center gap-4 text-sm">
    <span id="market-status" class="badge"></span>
    <span id="update-time" class="mono text-gray-500"></span>
    <span id="countdown" class="mono text-gray-600"></span>
  </div>
</div>

<!-- 核心指标卡片 -->
<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6" id="kpi-cards"></div>

<!-- 主内容区 -->
<div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
  <!-- 左列: Hot7 + 板块 -->
  <div class="space-y-6">
    <div class="card">
      <h2 class="text-sm font-medium text-gray-400 mb-4">HOT7 热门排行</h2>
      <div id="hot7-list" class="space-y-3"></div>
    </div>
    <div class="card">
      <h2 class="text-sm font-medium text-gray-400 mb-4">板块热度</h2>
      <div id="sector-chart" style="height:260px"></div>
    </div>
  </div>

  <!-- 中列: 精选个股 -->
  <div class="lg:col-span-2">
    <div class="card">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-medium text-gray-400">精选个股 (一致性评分)</h2>
        <span class="text-xs text-gray-600 mono">满分100 = 情绪25+板块20+龙头20+资金15+量价10+封单10</span>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-gray-500 text-xs border-b border-gray-800">
              <th class="text-left py-2 px-2">代码</th>
              <th class="text-left py-2 px-1">名称</th>
              <th class="text-right py-2 px-1">现价</th>
              <th class="text-right py-2 px-1">涨幅</th>
              <th class="text-right py-2 px-1">评分</th>
              <th class="py-2 px-1 text-center" style="min-width:160px">评分分布</th>
              <th class="text-right py-2 px-1">板块</th>
              <th class="text-right py-2 px-1">连涨</th>
            </tr>
          </thead>
          <tbody id="picks-table"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<!-- 新闻流 + 交易代理 -->
<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
  <div class="card">
    <h2 class="text-sm font-medium text-gray-400 mb-4">实时新闻流</h2>
    <div id="news-feed" class="space-y-2 max-h-96 overflow-y-auto pr-2"></div>
  </div>
  <div class="card">
    <h2 class="text-sm font-medium text-gray-400 mb-4">交易代理状态</h2>
    <div id="agent-status" class="space-y-3"></div>
  </div>
</div>

<!-- 数据注入 -->
<script>
const HOT7     = __HOT7__;
const PICKS    = __PICKS__;
const NEWS     = __NEWS__;
const SECTORS  = __SECTORS__;
const META     = __META__;

// 工具函数
function pctClass(v) { return v >= 0 ? 'up' : 'down'; }
function pctStr(v) { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'; }
function impactBadge(score) {
  if (score >= 80) return '<span class="badge badge-s">S</span>';
  if (score >= 65) return '<span class="badge badge-a">A</span>';
  if (score >= 50) return '<span class="badge badge-b">B</span>';
  return '<span class="badge badge-c">C</span>';
}
function barColor(score) {
  if (score >= 80) return '#ef4444';
  if (score >= 65) return '#f59e0b';
  if (score >= 50) return '#3b82f6';
  return '#64748b';
}

// 市场状态
function updateMarketStatus() {
  const el = document.getElementById('market-status');
  const now = new Date();
  const bjHour = (now.getUTCHours() + 8) % 24;
  const bjMin = now.getUTCMinutes();
  const t = bjHour * 100 + bjMin;
  const day = (now.getUTCDay() + (now.getUTCHours() + 8 >= 24 ? 1 : 0)) % 7;
  if (day === 0 || day === 6) {
    el.innerHTML = '<span class="badge" style="background:rgba(100,116,139,0.2);color:#94a3b8">休市</span>';
  } else if (t >= 930 && t <= 1130 || t >= 1300 && t <= 1500) {
    el.innerHTML = '<span class="badge" style="background:rgba(34,197,94,0.2);color:#22c55e"><span class="pulse">●</span>&nbsp;交易中</span>';
  } else if (t >= 915 && t < 930) {
    el.innerHTML = '<span class="badge" style="background:rgba(245,158,11,0.2);color:#f59e0b">集合竞价</span>';
  } else {
    el.innerHTML = '<span class="badge" style="background:rgba(100,116,139,0.2);color:#94a3b8">已收盘</span>';
  }
  document.getElementById('update-time').textContent = META.update_time || '';
}

// KPI 卡片
function renderKPI() {
  const container = document.getElementById('kpi-cards');
  const sentimentScore = META.sentiment_score || 50;
  const pickCount = PICKS.length;
  const topScore = PICKS.length > 0 ? PICKS[0].total : 0;
  const hotSector = SECTORS.length > 0 ? SECTORS[0].name : '-';

  const kpis = [
    { label: '市场情绪', value: sentimentScore.toFixed(0), unit: '分', color: sentimentScore >= 60 ? '#ef4444' : sentimentScore >= 40 ? '#f59e0b' : '#22c55e' },
    { label: '精选个股', value: pickCount, unit: '只', color: '#3b82f6' },
    { label: '最高评分', value: topScore.toFixed(1), unit: '分', color: topScore >= 80 ? '#ef4444' : '#f59e0b' },
    { label: '热门板块', value: hotSector, unit: '', color: '#8b5cf6' },
  ];

  container.innerHTML = kpis.map(k => `
    <div class="card glow" style="border-left: 3px solid ${k.color}">
      <p class="text-xs text-gray-500 mb-1">${k.label}</p>
      <p class="text-2xl font-bold mono" style="color:${k.color}">${k.value}<span class="text-sm text-gray-500 ml-1">${k.unit}</span></p>
    </div>
  `).join('');
}

// Hot7
function renderHot7() {
  const container = document.getElementById('hot7-list');
  if (!HOT7 || HOT7.length === 0) {
    container.innerHTML = '<p class="text-gray-600 text-sm">暂无数据</p>';
    return;
  }
  container.innerHTML = HOT7.map((item, i) => `
    <div class="flex items-center gap-3 py-2 ${i < HOT7.length - 1 ? 'border-b border-gray-800' : ''}">
      <span class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold
        ${i < 3 ? 'bg-red-500/20 text-red-400' : 'bg-gray-700 text-gray-400'}">${i+1}</span>
      <div class="flex-1 min-w-0">
        <p class="text-sm font-medium truncate">${item.name || item.symbol}</p>
        <p class="text-xs text-gray-500 mono">${item.symbol}</p>
      </div>
      <span class="text-xs text-gray-400">${item.mentions}次提及</span>
    </div>
  `).join('');
}

// 精选个股
function renderPicks() {
  const tbody = document.getElementById('picks-table');
  if (!PICKS || PICKS.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="text-center text-gray-600 py-8">暂无符合条件的个股</td></tr>';
    return;
  }
  tbody.innerHTML = PICKS.map(p => {
    const dims = [
      { name: '情绪', val: p.sentiment, w: 25 },
      { name: '板块', val: p.sector, w: 20 },
      { name: '龙头', val: p.leader, w: 20 },
      { name: '资金', val: p.fund, w: 15 },
      { name: '量价', val: p.vp, w: 10 },
      { name: '封单', val: p.seal, w: 10 },
    ];
    const miniBar = dims.map(d => {
      const pct = (d.val / 100 * d.w).toFixed(1);
      return `<div class="flex items-center gap-1" title="${d.name}: ${d.val.toFixed(0)}">
        <span class="text-gray-600" style="font-size:9px;width:18px">${d.name.substring(0,2)}</span>
        <div class="score-bar flex-1"><div class="score-bar-fill" style="width:${d.val}%;background:${barColor(d.val)}"></div></div>
      </div>`;
    }).join('');
    return `<tr class="border-b border-gray-800/50 hover:bg-gray-800/30">
      <td class="py-2.5 px-2 mono text-xs text-gray-400">${p.symbol}</td>
      <td class="py-2.5 px-1 font-medium text-sm">${p.name}</td>
      <td class="py-2.5 px-1 text-right mono text-sm">${p.price.toFixed(2)}</td>
      <td class="py-2.5 px-1 text-right mono text-sm ${pctClass(p.pct)}">${pctStr(p.pct)}</td>
      <td class="py-2.5 px-1 text-right">${impactBadge(p.total)} <span class="mono text-sm ml-1">${p.total.toFixed(1)}</span></td>
      <td class="py-2.5 px-1"><div class="space-y-0.5">${miniBar}</div></td>
      <td class="py-2.5 px-1 text-right text-xs text-gray-400">${p.sector_name || '-'}</td>
      <td class="py-2.5 px-1 text-right mono text-xs ${p.consecutive_ups >= 3 ? 'text-red-400' : 'text-gray-400'}">${p.consecutive_ups || 0}天</td>
    </tr>`;
  }).join('');
}

// 板块热度图
function renderSectorChart() {
  if (!SECTORS || SECTORS.length === 0) return;
  const chart = echarts.init(document.getElementById('sector-chart'), null, { renderer: 'svg' });
  const names = SECTORS.map(s => s.name);
  const counts = SECTORS.map(s => s.hit_count);
  chart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 80, right: 20, top: 10, bottom: 30 },
    xAxis: { type: 'value', axisLine: { lineStyle: { color: '#1e293b' } }, axisLabel: { color: '#64748b', fontSize: 11 }, splitLine: { lineStyle: { color: '#1e293b' } } },
    yAxis: { type: 'category', data: names.reverse(), axisLine: { lineStyle: { color: '#1e293b' } }, axisLabel: { color: '#94a3b8', fontSize: 12 } },
    series: [{
      type: 'bar', data: counts.reverse(), barWidth: 18,
      itemStyle: { borderRadius: [0, 4, 4, 0],
        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
          { offset: 0, color: '#3b82f6' }, { offset: 1, color: '#8b5cf6' }
        ])
      },
      label: { show: true, position: 'right', color: '#94a3b8', fontSize: 11 }
    }],
    tooltip: { trigger: 'axis', backgroundColor: '#1e293b', borderColor: '#334155', textStyle: { color: '#e2e8f0' } }
  });
  window.addEventListener('resize', () => chart.resize());
}

// 新闻流
function renderNews() {
  const container = document.getElementById('news-feed');
  const items = (NEWS || []).slice(0, 30);
  if (items.length === 0) {
    container.innerHTML = '<p class="text-gray-600 text-sm">暂无新闻</p>';
    return;
  }
  container.innerHTML = items.map(n => {
    const stockTag = n.stock_name ? `<span class="text-xs text-blue-400 ml-2">${n.stock_name}</span>` : '';
    return `<div class="py-2 border-b border-gray-800/50">
      <div class="flex items-start gap-2">
        <span class="mono text-xs text-gray-600 mt-0.5 shrink-0">${n.time_str || ''}</span>
        <p class="text-sm text-gray-300 leading-relaxed">${n.title}${stockTag}</p>
      </div>
    </div>`;
  }).join('');
}

// 交易代理状态
function renderAgentStatus() {
  const container = document.getElementById('agent-status');
  const stateColors = {
    'IDLE': '#64748b', 'OBSERVE': '#f59e0b', 'READY': '#3b82f6',
    'HOLD': '#ef4444', 'EXIT': '#22c55e'
  };
  const agents = META.agents || [];
  if (agents.length === 0) {
    container.innerHTML = '<p class="text-gray-600 text-sm">无活跃交易代理</p>';
    return;
  }
  container.innerHTML = agents.map(a => `
    <div class="flex items-center justify-between py-2 border-b border-gray-800/50">
      <div class="flex items-center gap-3">
        <span class="w-2 h-2 rounded-full" style="background:${stateColors[a.state] || '#64748b'}"></span>
        <div>
          <span class="text-sm font-medium">${a.name || a.symbol}</span>
          <span class="mono text-xs text-gray-500 ml-2">${a.symbol}</span>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <span class="badge" style="background:${stateColors[a.state]}22;color:${stateColors[a.state]}">${a.state}</span>
        <span class="mono text-xs text-gray-400">评分 ${a.score}</span>
      </div>
    </div>
  `).join('');
}

// 倒计时
let nextRefresh = 180;
function updateCountdown() {
  nextRefresh--;
  if (nextRefresh <= 0) {
    location.reload();
    return;
  }
  document.getElementById('countdown').textContent = `刷新 ${nextRefresh}s`;
}

// 初始化
updateMarketStatus();
renderKPI();
renderHot7();
renderPicks();
renderSectorChart();
renderNews();
renderAgentStatus();
setInterval(updateCountdown, 1000);
setInterval(updateMarketStatus, 30000);
</script>
</body>
</html>"""


def generate_html(hot7, picks, news, sectors, extra_meta=None):
    """生成 HTML 面板"""
    meta = {
        "update_time": now_bj().strftime("%Y-%m-%d %H:%M:%S"),
        "sentiment_score": analyze_sentiment(news),
        "agents": [],
    }
    if extra_meta:
        meta.update(extra_meta)

    html = HTML_TEMPLATE
    html = html.replace("__HOT7__", json.dumps(hot7[:7], ensure_ascii=False))
    html = html.replace("__PICKS__", json.dumps(picks[:20], ensure_ascii=False))
    html = html.replace("__NEWS__", json.dumps(news[:50], ensure_ascii=False))
    html = html.replace("__SECTORS__", json.dumps(sectors[:8], ensure_ascii=False))
    html = html.replace("__META__", json.dumps(meta, ensure_ascii=False))

    return html


# ──────────────────────── HTTP 服务器 ────────────────────────

class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


class DashboardHandler(SimpleHTTPRequestHandler):
    """面板 HTTP 请求处理"""
    html_content = ""

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            content = DashboardHandler.html_content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(content))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # 静默日志


_serve_stop = threading.Event()


def serve_mode(port=8080):
    """
    服务模式:
    - HTTP 面板服务
    - 每3分钟自动刷新数据
    - 交易日定时飞书推送 (9:30, 11:30, 14:30)
    - 重大新闻即时提醒
    """
    print(f"\n{'='*60}")
    print(f"  A股利好监控 - 服务模式")
    print(f"  端口: {port} | 刷新间隔: 3分钟")
    print(f"  飞书: {'已配置' if FEISHU_WEBHOOK else '未配置'}")
    print(f"  Telegram: {'已配置' if TG_TOKEN else '未配置'}")
    print(f"{'='*60}\n")

    # 首次刷新
    _refresh_dashboard()

    # 启动 HTTP 服务
    server = ReusableHTTPServer(("0.0.0.0", port), DashboardHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"  面板已启动: http://0.0.0.0:{port}")

    # 定时推送记录
    pushed_today = set()
    push_times = [(9, 30), (11, 30), (14, 30)]

    # 主循环
    while not _serve_stop.is_set():
        try:
            time.sleep(180)  # 3分钟
            _refresh_dashboard()

            # 定时推送
            now = now_bj()
            for ph, pm in push_times:
                key = f"{now.date()}-{ph}:{pm}"
                if key not in pushed_today:
                    if now.hour == ph and now.minute >= pm and now.minute < pm + 5:
                        if now.weekday() < 5:
                            _scheduled_push()
                            pushed_today.add(key)

            # 清理前日推送记录
            today_str = str(now.date())
            pushed_today = {k for k in pushed_today if k.startswith(today_str)}

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"  [ERROR] 刷新异常: {e}")
            time.sleep(30)

    server.shutdown()
    print("  服务已停止")


def _refresh_dashboard():
    """刷新面板数据"""
    try:
        hot7, picks, quotes, news, sectors = run_pipeline()

        # 重大新闻检测
        check_breaking_news(news)

        # 更新面板
        html = generate_html(hot7, picks, news, sectors)
        DashboardHandler.html_content = html

        # 同时写入文件
        with open("dashboard.html", "w", encoding="utf-8") as f:
            f.write(html)

        print(f"  [{now_bj().strftime('%H:%M:%S')}] 面板已刷新")
    except Exception as e:
        print(f"  [ERROR] 刷新失败: {e}")


def _scheduled_push():
    """定时飞书推送"""
    try:
        hot7, picks, quotes, news, sectors = run_pipeline()
        sent_score = analyze_sentiment(news)

        lines = [
            f"**市场情绪**: {sent_score:.0f}分",
            f"**精选个股**: {len(picks)}只",
            f"**热门板块**: {', '.join(s['name'] for s in sectors[:3])}",
        ]

        push_feishu("定时监控报告", lines, picks)
        push_telegram(f"📊 A股监控\n情绪: {sent_score:.0f}\n精选: {len(picks)}只")
    except Exception as e:
        print(f"  [ERROR] 定时推送失败: {e}")


# ──────────────────────── CLI 入口 ────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="A股利好监控 + 短线量化交易系统")
    parser.add_argument("--mode", choices=["live", "backtest", "calibrate", "serve"],
                        default="live", help="运行模式")
    parser.add_argument("--port", type=int, default=8080, help="服务端口")
    parser.add_argument("--days", type=int, default=60, help="回测天数")
    parser.add_argument("--sectors", nargs="+", help="回测板块")
    parser.add_argument("--output", default="dashboard.html", help="输出文件")
    parser.add_argument("--auto", action="store_true", help="自动标定参数")

    args = parser.parse_args()

    if args.auto:
        args.mode = "calibrate"

    if args.mode == "live":
        print("运行模式: LIVE (实盘监控)")
        hot7, picks, quotes, news, sectors = run_pipeline()
        html = generate_html(hot7, picks, news, sectors)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n面板已生成: {args.output}")

        # 推送
        if picks:
            sent_score = analyze_sentiment(news)
            lines = [
                f"**市场情绪**: {sent_score:.0f}分",
                f"**精选个股**: {len(picks)}只",
            ]
            push_feishu("实盘监控报告", lines, picks)

    elif args.mode == "backtest":
        print("运行模式: BACKTEST (回测)")
        sectors = args.sectors or list(SEED_POOLS.keys())[:3]
        trades, stats = run_backtest(days=args.days, sectors=sectors)
        print(f"\n交易记录 ({len(trades)} 笔):")
        for t in trades:
            print(f"  {t['entry_date']} 买入 {t['symbol']} @{t['entry_price']} → "
                  f"{t['exit_date']} 卖出 @{t['exit_price']} ({t['profit_pct']:+.2f}%) [{t['signal']}]")

    elif args.mode == "calibrate":
        print("运行模式: CALIBRATION (参数标定)")
        sectors = args.sectors or list(SEED_POOLS.keys())[:3]
        best = run_calibration(days=args.days, sectors=sectors)

    elif args.mode == "serve":
        print("运行模式: SERVE (服务)")
        serve_mode(port=args.port)


if __name__ == "__main__":
    main()
