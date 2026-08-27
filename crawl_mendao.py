# -*- coding: utf-8 -*-
"""
门道商机爬虫（得物官方搬砖工具）—— 差异化线报版
==============================================
用法:
  python crawl_mendao.py 11610567                       # 爬指定 carryId
  python crawl_mendao.py --seed 11610567 --depth 2      # 顺藤摸瓜扩 2 层
  python crawl_mendao.py --seed 11610567 --depth 2 --avoid-hot 5 --since-hours 168
  python crawl_mendao.py --from-snapshot                # 无网时用历史快照建候选池

说明:
  - 优先 requests 直连；被墙/被反爬时自动改用 playwright 无头浏览器
  - 页面无需登录；HTML 内嵌 carryId 可无限顺藤摸瓜
  - "利润"是毛差 = 得物价 - 到手价；净利 = 毛差 - 得物扣费
  - 费率/转账/固定费/目标利润统一读 config/rates.json（T1 配置外置）
  - 曝光追踪 data/exposure.json；候选池 data/pool.json
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ROOT, "config", "rates.json")
DATA = os.path.join(ROOT, "data")
EXPOSURE = os.path.join(DATA, "exposure.json")
POOL = os.path.join(DATA, "pool.json")
SNAPSHOT = os.path.join(ROOT, "data", "snapshot.json")

BASE = "https://deal.mendaoapp.com/page/carry-referee?carryId={}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://deal.mendaoapp.com/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}
SLEEP = 1.2


# ---------- 配置 ----------

def load_rates():
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("category_rates", {})
    cfg.setdefault("transfer_rate", 0.01)
    cfg.setdefault("fixed_fee", 15)
    cfg.setdefault("target_profit", 50)
    cfg.setdefault("min_net_profit", 50)
    return cfg


def load_exposure():
    try:
        with open(EXPOSURE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_pool_map():
    try:
        with open(POOL, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {str(d.get("carry_id")): d for d in data if d.get("carry_id")}
        return {str(k): v for k, v in data.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---------- 类目识别 ----------

CATEGORY_RULES = [
    (["鞋", "板鞋", "跑鞋", "钉鞋", "篮球鞋", "帆布鞋", "休闲鞋", "CAMPUS", "AF1", "Dunk", "Superstar", "Gazelle", "Maxfly"], "球鞋"),
    (["口红", "粉底", "香水", "精华", "面霜", "眼影", "气垫", "护肤", "面膜", "防晒", "洁面", "唇釉", "腮红"], "美妆"),
    (["手办", "盲盒", "模型", "积木", "玩偶", "雕像", "机甲", "潮玩"], "潮玩"),
    (["耳机", "音箱", "手表", "手机", "平板", "键盘", "鼠标", "充电宝", "手环", "相机"], "数码"),
    (["羽绒", "外套", "夹克", "卫衣", "T恤", "T 恤", "裤", "衬衫", "毛衣", "裙", "棉服", "大衣", "马甲", "风衣"], "服饰"),
    (["背包", "斜挎包", "双肩包", "胸包", "腰包", "挎包", "冲锋衣", "登山", "帐篷", "睡袋", "腰包"], "户外"),
]


def classify_category(title):
    t = title or ""
    for kws, cat in CATEGORY_RULES:
        if any(k in t for k in kws):
            return cat
    return "其他"


# ---------- 抓取 ----------

def fetch_requests(carry_id):
    import requests
    r = requests.get(BASE.format(carry_id), headers=HEADERS, timeout=15)
    r.encoding = "utf-8"
    return r.text


def fetch_browser(carry_id):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.goto(BASE.format(carry_id), timeout=30000)
        pg.wait_for_timeout(3200)
        text = pg.evaluate("document.body.innerText")
        html = pg.content()
        b.close()
        return text, html


def fetch_page(carry_id, use_browser=False):
    """返回 (text, html)；requests 失败自动降级 playwright。"""
    if not use_browser:
        try:
            html = fetch_requests(carry_id)
            text = re.sub(r"<script[\s\S]*?</script>", "", html)
            text = re.sub(r"<[^>]+>", "\n", text)
            return text, html
        except Exception as e:
            print("  [warn] requests 失败，尝试 playwright:", str(e)[:100])
    return fetch_browser(carry_id)


def fetch_and_parse(carry_id, use_browser=False):
    """抓取并解析；requests 模式解析为空时自动降级 playwright 重试一次。"""
    text, html = fetch_page(carry_id, use_browser=use_browser)
    parsed = parse(text, html)
    if not use_browser and not parsed.get("title") and not parsed.get("article_no"):
        print("  [warn] requests 解析为空，改用 playwright 重试")
        try:
            text, html = fetch_browser(carry_id)
            parsed = parse(text, html)
        except Exception as e:
            print("  [warn] playwright 也失败:", str(e)[:100])
    return parsed, text, html


# ---------- 解析 ----------

def parse(text, html):
    def g(regex):
        m = re.search(regex, text)
        return m.group(1).strip() if m else None

    ids = list(dict.fromkeys(re.findall(r'carryId["\\]?\s*:\s*"?(\d+)', html)))

    name = g(r"该商机\s*\n?\s*([^\n]{4,80})")
    if not name:
        m = re.search(r"([^\n]{4,80}?)\s*\n\s*货号[:：]", text)
        name = m.group(1).strip() if m else None

    profit = g(r"利润\s*[¥￥]\s*([\d.]+)")
    low = g(r"最低价\s*[¥￥]\s*([\d.]+)")
    buy = g(r"到手价\s*[¥￥]\s*([\d.]+)")
    want = g(r"(\d+)\s*人想买")
    sales = g(r"(?:7日销量|近7天销量|近7日销量|7天销量)[^\d]{0,15}(\d+)")
    if not sales:
        sales = g(r"销量[:：]?\s*(\d+)")
    time_str = g(r"(\d+月\d+日\s*\d+:\d+)\s*发布")
    color = g(r"颜色[:：]\s*([^\n]{1,24})") or g(r"配色[:：]\s*([^\n]{1,24})")
    size = g(r"尺码[:：]\s*([^\n]{1,24})")

    def num(x):
        return float(x) if x else None

    return {
        "title": name,
        "article_no": g(r"货号[:：]\s*(\S+)"),
        "color": color,
        "size": size,
        "gross_profit": num(profit),
        "du_price": num(low),
        "cost": num(buy),
        "want_count": int(want) if want else None,
        "sales_7d": int(sales) if sales else None,
        "published_raw": time_str,
        "sub_carry_ids": ids,
    }


def parse_publish(dt_str):
    """'8月26日 14:22' -> ISO '2026-08-26T14:22'（跨年按当前年回退）。"""
    if not dt_str:
        return None
    m = re.match(r"(\d+)月(\d+)日\s*(\d+):(\d+)", dt_str)
    if not m:
        return None
    mon, day, hh, mm = (int(x) for x in m.groups())
    now = datetime.now()
    year = now.year
    if (mon, day) > (now.month, now.day):
        year -= 1
    try:
        return datetime(year, mon, day, hh, mm).isoformat(timespec="minutes")
    except ValueError:
        return None


def compute_net(item, rates):
    """净利 = 得物价 - (得物价*(类目费率+转账) + 固定费) - 到手价。"""
    low, buy = item.get("du_price"), item.get("cost")
    if low is None or buy is None:
        return None
    cat = item.get("category") or "其他"
    rate = rates["category_rates"].get(cat, 0.10) + rates["transfer_rate"]
    fee = round(low * rate + rates["fixed_fee"], 2)
    return round(low - fee - buy, 2)


# ---------- 曝光与候选池 ----------

def touch_exposure(exposure, carry_id, ts):
    e = exposure.get(carry_id, {})
    e["first_seen"] = e.get("first_seen", ts)
    e["seen_count"] = int(e.get("seen_count", 0)) + 1
    e["last_seen"] = ts
    exposure[carry_id] = e
    return e


def to_pool_item(carry_id, parsed, rates, exp, ts):
    item = {
        "carry_id": carry_id,
        "title": parsed.get("title"),
        "article_no": parsed.get("article_no"),
        "color": parsed.get("color"),
        "size": parsed.get("size"),
        "gross_profit": parsed.get("gross_profit"),
        "du_price": parsed.get("du_price"),
        "cost": parsed.get("cost"),
        "want_count": parsed.get("want_count"),
        "sales_7d": parsed.get("sales_7d"),
        "published_at": parse_publish(parsed.get("published_raw")),
        "category": classify_category(parsed.get("title")),
        "url": BASE.format(carry_id),
    }
    item["net_profit"] = compute_net(item, rates)
    item["first_seen"] = exp.get("first_seen", ts)
    item["last_seen"] = exp.get("last_seen", ts)
    item["seen_count"] = exp.get("seen_count", 1)
    return item


def within_hours(published_at, hours):
    if not published_at or hours is None:
        return True
    try:
        dt = datetime.fromisoformat(published_at)
    except ValueError:
        return True
    now = datetime.now()
    if dt.tzinfo is not None and now.tzinfo is None:
        dt = dt.replace(tzinfo=None)
    return (now - dt) <= timedelta(hours=hours)


# ---------- 快照建池（无网兜底） ----------

def build_from_snapshot(rates, snapshot_path=None):
    path = snapshot_path or SNAPSHOT
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    ts = now_iso()
    exposure = load_exposure()
    pool = load_pool_map()
    new_count = 0
    for row in rows:
        link = row.get("link") or ""
        m = re.search(r"carryId=(\d+)", link)
        carry_id = m.group(1) if m else None
        if not carry_id:
            continue
        exp = touch_exposure(exposure, carry_id, ts)
        sc = (row.get("size_color") or "").strip()
        color, size = sc, None
        m2 = re.search(r"([A-Za-z0-9.]+|均码|女款|男款)\s*$", sc)
        if m2:
            size = m2.group(1)
            color = sc[: m2.start()].strip() or size
        item = {
            "carry_id": carry_id,
            "title": row.get("name"),
            "article_no": row.get("code"),
            "color": color,
            "size": size,
            "gross_profit": round((row.get("low_price_dewu") or 0) - (row.get("buy") or 0), 2) if row.get("buy") and row.get("low_price_dewu") else None,
            "du_price": row.get("low_price_dewu"),
            "cost": row.get("buy"),
            "want_count": None,
            "sales_7d": int(row["sales7"]) if str(row.get("sales7") or "").isdigit() else None,
            "published_at": None,
            "category": row.get("cat") or classify_category(row.get("name")),
            "url": link,
            "net_profit": None,
            "first_seen": exp["first_seen"],
            "last_seen": ts,
            "seen_count": exp["seen_count"],
        }
        item["net_profit"] = compute_net(item, rates)
        if carry_id in pool:
            keep = pool[carry_id]
            keep.update({k: v for k, v in item.items() if k != "first_seen"})
            keep["first_seen"] = keep.get("first_seen", exp["first_seen"])
            keep["seen_count"] = exp["seen_count"]
            keep["last_seen"] = ts
            pool[carry_id] = keep
        else:
            pool[carry_id] = item
            new_count += 1
    save_json(EXPOSURE, exposure)
    save_json(POOL, list(pool.values()))
    print(f"[快照建池] 总 {len(pool)} 条（新增 {new_count}）-> {POOL}")
    return len(pool)


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser(description="门道商机爬虫（差异化线报版）")
    ap.add_argument("ids", nargs="*", help="carryId 列表")
    ap.add_argument("--seed", help="种子 carryId")
    ap.add_argument("--depth", type=int, default=1, help="顺藤摸瓜层数")
    ap.add_argument("--avoid-hot", type=int, default=0, help="seen_count>=N 的 ID 跳过")
    ap.add_argument("--since-hours", type=float, default=None, help="只保留发布 N 小时内的商机")
    ap.add_argument("--from-snapshot", action="store_true", help="无网时用历史快照建候选池")
    ap.add_argument("--fallback-snapshot", action="store_true", help="实时抓取 0 条成功时自动回退快照建池")
    ap.add_argument("--snapshot", default=SNAPSHOT, help="快照 JSON 路径")
    ap.add_argument("--browser", action="store_true", help="强制用无头浏览器")
    ap.add_argument("--sleep", type=float, default=SLEEP, help="请求间隔秒数")
    args = ap.parse_args()

    rates = load_rates()
    if args.from_snapshot:
        build_from_snapshot(rates, args.snapshot)
        return

    exposure = load_exposure()
    pool = load_pool_map()
    ts = now_iso()

    # 决定要爬的 ID 队列（BFS 顺藤摸瓜）
    queue = list(args.ids)
    if args.seed:
        queue = [args.seed]
    seen_queue = set()
    hot_skip = 0
    failed = 0
    parsed_count = 0
    new_count = 0

    for _ in range(args.depth):
        nxt = []
        for cid in queue:
            cid = str(cid)
            if cid in seen_queue:
                continue
            seen_queue.add(cid)
            prev = exposure.get(cid, {}).get("seen_count", 0)
            if args.avoid_hot and prev >= args.avoid_hot:
                hot_skip += 1
                print(f"[HOT_SKIPPED] {cid} 已见 {prev} 次，跳过")
                continue
            try:
                parsed, text, html = fetch_and_parse(cid, use_browser=args.browser)
                if not parsed.get("title") and not parsed.get("article_no"):
                    failed += 1
                    print(f"[{cid}] 解析失败")
                else:
                    exp = touch_exposure(exposure, cid, ts)
                    item = to_pool_item(cid, parsed, rates, exp, ts)
                    is_new = cid not in pool
                    pool[cid] = item
                    if is_new:
                        new_count += 1
                    parsed_count += 1
                    print(f"[{cid}] {item['title'] or '?'} 净利{item['net_profit']}")
                nxt.extend(parsed.get("sub_carry_ids", []) or [])
            except Exception as e:
                failed += 1
                print(f"[{cid}] 抓取失败: {str(e)[:100]}")
            time.sleep(args.sleep)
        queue = [str(x) for x in dict.fromkeys(nxt)][:20]

    if args.fallback_snapshot and parsed_count == 0:
        print("[fallback] 实时抓取 0 条成功，回退快照建池")
        build_from_snapshot(rates, args.snapshot)
        return

    # --since-hours 过滤
    if args.since_hours:
        pool = {k: v for k, v in pool.items() if within_hours(v.get("published_at"), args.since_hours)}

    save_json(EXPOSURE, exposure)
    save_json(POOL, list(pool.values()))

    total = len(pool)
    print("-" * 50)
    print(f"汇总：总 {total} 条 | 本次新增 {new_count} | HOT跳过 {hot_skip} | 解析/抓取失败 {failed}")
    print("exposure:", EXPOSURE)
    print("pool:", POOL)


if __name__ == "__main__":
    main()
