# -*- coding: utf-8 -*-
"""
稀缺分打分：data/pool.json -> data/scored.json
================================================
稀缺分 = 净利 x W时效 x W供需 x W类目 x (1 - 曝光系数)

因子含义（详见 DIFF_STRATEGY.md）：
  W时效   发布<12h=0.5（首发窗口主动避让，不跟单）
          12~48h=1.0（冷静期） 48~168h=1.3（真需求确认）
          >168h=过期（分数置0，保留观察） 缺发布时间=1.0
  W供需   min(想买人数/max(7日销量,1),5)/5 映射到 [0.2,1.0]；缺想买人数=0.8
  W类目   读 config/tiers.json：冷门加权x1.3、热门降权x0.7、其余x1.0
  曝光系数 min(seen_count/10,1)：被抓10次以上视为全网皆知，分数归零
边界：净利<=min_net_profit 的条目不参与排序但仍输出；所有除法防除零。
"""
import json
import os
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RATES = os.path.join(ROOT, "config", "rates.json")
TIERS = os.path.join(ROOT, "config", "tiers.json")
POOL = os.path.join(ROOT, "data", "pool.json")
SCORED = os.path.join(ROOT, "data", "scored.json")

CATEGORY_ALIAS = {"户外配饰": "户外"}  # tiers.json 里“户外配饰”对应候选池类目“户外”


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def load_config():
    rates = load_json(RATES, {})
    rates.setdefault("category_rates", {})
    rates.setdefault("transfer_rate", 0.01)
    rates.setdefault("fixed_fee", 15)
    rates.setdefault("min_net_profit", 50)
    rates.setdefault("cold_pick_threshold", 80)
    tiers = load_json(TIERS, {})
    boost = {CATEGORY_ALIAS.get(x, x) for x in tiers.get("冷门加权", [])}
    cut = {CATEGORY_ALIAS.get(x, x) for x in tiers.get("热门降权", [])}
    return rates, boost, cut


def age_hours(published_at, now=None):
    if not published_at:
        return None
    try:
        dt = datetime.fromisoformat(published_at)
    except (ValueError, TypeError):
        return None
    now = now or datetime.now()
    if dt.tzinfo is not None and now.tzinfo is None:
        dt = dt.replace(tzinfo=None)
    return (now - dt).total_seconds() / 3600.0


def time_factor(age_h):
    if age_h is None:
        return 1.0, "时效未知"
    if age_h < 12:
        return 0.5, "首发窗口·避让"
    if age_h <= 48:
        return 1.0, "冷静期中"
    if age_h <= 168:
        return 1.3, "真需求确认"
    return 0.0, "过期"


def supply_demand_factor(want, sales):
    if want is None:
        return 0.8
    ratio = min(want / max(int(sales or 0), 1), 5) / 5.0
    return round(0.2 + 0.8 * ratio, 4)


def category_factor(cat, boost, cut):
    if cat in boost:
        return 1.3
    if cat in cut:
        return 0.7
    return 1.0


def exposure_factor(seen_count):
    return min(int(seen_count or 0) / 10.0, 1.0)


def compute_net(item, rates):
    low, buy = item.get("du_price"), item.get("cost")
    if low is None or buy is None:
        return None
    cat = item.get("category") or "其他"
    rate = rates["category_rates"].get(cat, 0.10) + rates["transfer_rate"]
    fee = round(low * rate + rates["fixed_fee"], 2)
    return round(low - fee - buy, 2)


def score_item(item, rates, boost, cut, now=None):
    net = item.get("net_profit")
    if net is None:
        net = compute_net(item, rates)
    age = age_hours(item.get("published_at"), now)
    w_time, label = time_factor(age)
    w_sup = supply_demand_factor(item.get("want_count"), item.get("sales_7d"))
    w_cat = category_factor(item.get("category"), boost, cut)
    exp = exposure_factor(item.get("seen_count"))
    seen = int(item.get("seen_count") or 0)

    score = None
    if net is not None and (age is None or age <= 168):
        score = round(net * w_time * w_sup * w_cat * (1 - exp), 1)

    if age is not None and age > 168:
        verdict = "过期"
        score = 0
    elif seen >= 10:
        verdict = "黑名单"
        score = 0
    elif net is not None and net >= rates["min_net_profit"] and score is not None and score >= rates["cold_pick_threshold"]:
        verdict = "冷门优选"
    elif net is not None and net >= rates["min_net_profit"]:
        verdict = "普通"
    else:
        verdict = "普通"

    return {
        "net_profit": net,
        "scarcity_score": score,
        "verdict": verdict,
        "time_label": label,
        "w_time": w_time,
        "w_supply_demand": w_sup,
        "w_category": w_cat,
        "exposure_coeff": round(exp, 3),
    }


def main():
    rates, boost, cut = load_config()
    pool = load_json(POOL, [])
    if not isinstance(pool, list):
        pool = list(pool.values())

    items = []
    for it in pool:
        merged = dict(it)
        merged.update(score_item(it, rates, boost, cut))
        items.append(merged)

    # 净利达标者可排名，按稀缺分降序；不达标者仍输出但排在后面
    ranked = [x for x in items if x["net_profit"] is not None and x["net_profit"] >= rates["min_net_profit"]]
    others = [x for x in items if x not in ranked]
    ranked.sort(key=lambda x: (x["scarcity_score"] or 0), reverse=True)
    others.sort(key=lambda x: (x["scarcity_score"] or 0), reverse=True)
    out = ranked + others

    os.makedirs(os.path.dirname(SCORED), exist_ok=True)
    with open(SCORED, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    cold = sum(1 for x in out if x["verdict"] == "冷门优选")
    expired = sum(1 for x in out if x["verdict"] == "过期")
    black = sum(1 for x in out if x["verdict"] == "黑名单")
    print(f"scored: {len(out)} 条 | 冷门优选 {cold} | 普通 {len(out)-cold-expired-black} | 过期 {expired} | 黑名单 {black}")
    print("saved:", SCORED)


if __name__ == "__main__":
    main()
