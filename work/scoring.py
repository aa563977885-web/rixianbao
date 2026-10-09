# -*- coding: utf-8 -*-
"""
稀缺分打分 v2：data/pool.json -> data/scored.json
================================================
稀缺分 = 净利 x W时效 x W供需 x W类目 x (1 - 曝光系数)

v2 新增：
  「可蹲」判定（DIFF_STRATEGY 反向用法落地）：
      seen>=10（热度已过） 且 净利>=min_net_profit 且 平台仍在售（last_seen<=72h）
      -> 竞争者已散场，独享剩余利润；价格轨迹在跌的标「可蹲·降价中」
  账单先验：config/ledger_prior.json 存自己账单算出的类目真实盈利分，
      类目因子 = (静态冷热门分 + 账单分) / 2；无先验文件时退回静态分

因子含义（详见 DIFF_STRATEGY.md）：
  W时效   发布<12h=0.5（首发窗口主动避让，不跟单）
          12~48h=1.0（冷静期） 48~168h=1.3（真需求确认）
          >168h=过期（分数置0，保留观察） 缺发布时间=1.0
  W供需   min(想买人数/max(7日销量,1),5)/5 映射到 [0.2,1.0]；缺想买人数=0.8
  W类目   tiers.json 冷热门分 与 ledger_prior.json 账单分取均值
  曝光系数 min(seen_count/10,1)：被抓10次以上视为全网皆知（冷门线路上分数归零，
          但满足条件的会转入「可蹲」赛道重新评估）
边界：净利<=min_net_profit 的条目不参与排序但仍输出；所有除法防除零。
"""
import json
import os
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RATES = os.path.join(ROOT, "config", "rates.json")
TIERS = os.path.join(ROOT, "config", "tiers.json")
PRIOR = os.path.join(ROOT, "config", "ledger_prior.json")
POOL = os.path.join(ROOT, "data", "pool.json")
SCORED = os.path.join(ROOT, "data", "scored.json")
PRICE_HISTORY = os.path.join(ROOT, "data", "price_history.json")

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
    prior = load_json(PRIOR, {})
    if isinstance(prior, dict) and isinstance(prior.get("prior"), dict):
        prior = prior["prior"]  # ledger_prior.py 的嵌套格式
    return rates, boost, cut, prior


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


def blended_category_factor(cat, boost, cut, prior):
    """类目因子 = (冷热门静态分 + 账单先验分) / 2；先验缺失时退回静态分。"""
    tier = category_factor(cat, boost, cut)
    p = prior.get(cat) or prior.get(CATEGORY_ALIAS.get(cat, cat)) or {}
    if isinstance(p, dict):
        p = p.get("factor")
    if isinstance(p, (int, float)) and 0.5 <= p <= 1.6:
        return round((tier + p) / 2, 3)
    return tier


def price_trend(carry_id, history):
    """价格轨迹 -> {'first','last','pct','n'}；不足2条或无价返回 None。"""
    seq = history.get(str(carry_id)) or []
    pts = [p for p in seq if isinstance(p, (list, tuple)) and p[1] is not None]
    if len(pts) < 2:
        return None
    first, last = float(pts[0][1]), float(pts[-1][1])
    if first <= 0:
        return None
    return {"first": first, "last": last, "pct": round((last - first) / first * 100, 1), "n": len(pts)}


def last_seen_fresh(item, hours=72, now=None):
    ls = item.get("last_seen")
    if not ls:
        return False
    try:
        dt = datetime.fromisoformat(str(ls))
    except ValueError:
        return False
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    now = now or datetime.now()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    return (now - dt).total_seconds() <= hours * 3600


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


def score_item(item, rates, boost, cut, prior, history, now=None):
    # 联盟源（tbk/jd）条目：得物价未知，不参与稀缺分，归「待核价」由 App 核价
    if item.get("source") in ("tbk", "jd") and item.get("du_price") is None:
        trend = price_trend(item.get("carry_id"), history)
        out = {
            "net_profit": None,
            "scarcity_score": None,
            "verdict": "待核价",
            "time_label": "待App核价",
            "w_time": None,
            "w_supply_demand": None,
            "w_category": None,
            "exposure_coeff": 0.0,
        }
        if trend:
            out["price_trend"] = trend
        return out

    net = item.get("net_profit")
    if net is None:
        net = compute_net(item, rates)
    age = age_hours(item.get("published_at"), now)
    w_time, label = time_factor(age)
    w_sup = supply_demand_factor(item.get("want_count"), item.get("sales_7d"))
    w_cat = blended_category_factor(item.get("category"), boost, cut, prior)
    exp = exposure_factor(item.get("seen_count"))
    seen = int(item.get("seen_count") or 0)
    trend = price_trend(item.get("carry_id"), history)

    score = None
    if net is not None and (age is None or age <= 168):
        score = round(net * w_time * w_sup * w_cat * (1 - exp), 1)

    verdict = "普通"
    if age is not None and age > 168:
        verdict = "过期"
        score = 0
    elif seen >= 10:
        # 热度已过：仍然在售且仍有达标净利 -> 「可蹲」（反向打法）；否则黑名单
        if net is not None and net >= rates["min_net_profit"] and last_seen_fresh(item, now=now):
            verdict = "可蹲·降价中" if (trend and trend["pct"] <= -3) else "可蹲"
            # 盯款雷达排序用：热度中性分 = 净利 × 类目分
            score = round(net * w_cat, 1)
        else:
            verdict = "黑名单"
            score = 0
    elif net is not None and net >= rates["min_net_profit"] and score is not None and score >= rates["cold_pick_threshold"]:
        verdict = "冷门优选"

    out = {
        "net_profit": net,
        "scarcity_score": score,
        "verdict": verdict,
        "time_label": label,
        "w_time": w_time,
        "w_supply_demand": w_sup,
        "w_category": w_cat,
        "exposure_coeff": round(exp, 3),
    }
    if trend:
        out["price_trend"] = trend
    return out


def main():
    rates, boost, cut, prior = load_config()
    history = load_json(PRICE_HISTORY, {})
    pool = load_json(POOL, [])
    if not isinstance(pool, list):
        pool = list(pool.values())

    items = []
    for it in pool:
        merged = dict(it)
        merged.update(score_item(it, rates, boost, cut, prior, history))
        items.append(merged)

    # 排序：verdict 分组内按分数降序；组间 今日机会 > 可蹲 > 黑名单 > 过期 > 其他
    def verdict_rank(v):
        return {"待核价": -1, "冷门优选": 0, "普通": 1, "可蹲·降价中": 2, "可蹲": 3, "黑名单": 4, "过期": 5}.get(v, 6)

    items.sort(key=lambda x: (verdict_rank(x["verdict"]), -(x["scarcity_score"] or 0)))
    out = items

    os.makedirs(os.path.dirname(SCORED), exist_ok=True)
    with open(SCORED, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    cold = sum(1 for x in out if x["verdict"] == "冷门优选")
    watch = sum(1 for x in out if x["verdict"] in ("可蹲", "可蹲·降价中"))
    verify = sum(1 for x in out if x["verdict"] == "待核价")
    expired = sum(1 for x in out if x["verdict"] == "过期")
    black = sum(1 for x in out if x["verdict"] == "黑名单")
    print(f"scored: {len(out)} 条 | 待核价 {verify} | 冷门优选 {cold} | 可蹲 {watch} | 黑名单 {black} | 过期 {expired} | 普通 {len(out)-verify-cold-watch-expired-black}")
    print("saved:", SCORED)


if __name__ == "__main__":
    main()
