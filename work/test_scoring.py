# -*- coding: utf-8 -*-
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scoring

RATES = {
    "category_rates": {"球鞋": 0.12, "服饰": 0.10, "户外": 0.10, "美妆": 0.08, "潮玩": 0.12, "数码": 0.06, "其他": 0.10},
    "transfer_rate": 0.01,
    "fixed_fee": 15,
    "min_net_profit": 50,
    "cold_pick_threshold": 80,
}
BOOST = {"美妆", "户外"}
CUT = {"球鞋"}
PRIOR = {}          # 账单先验，v2
HISTORY = {}        # 价格轨迹，v2
NOW = datetime(2026, 8, 27, 12, 0, 0)


def iso(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).isoformat(timespec="minutes")


def base(**kw):
    d = dict(
        title="测试品", article_no="X1", category="其他", du_price=500, cost=300,
        want_count=50, sales_7d=10, published_at=iso(24), seen_count=0,
    )
    d.update(kw)
    return d


def score(item, prior=None, history=None, now=NOW):
    return scoring.score_item(item, RATES, BOOST, CUT, PRIOR if prior is None else prior,
                              HISTORY if history is None else history, now=now)


class TestScoring(unittest.TestCase):
    def test_time_windows_4_branches(self):
        r = score(base(published_at=iso(6)))
        self.assertEqual(r["w_time"], 0.5)
        self.assertEqual(r["time_label"], "首发窗口·避让")
        r = score(base(published_at=iso(30)))
        self.assertEqual(r["w_time"], 1.0)
        self.assertEqual(r["time_label"], "冷静期中")
        r = score(base(published_at=iso(100)))
        self.assertEqual(r["w_time"], 1.3)
        self.assertEqual(r["time_label"], "真需求确认")
        r = score(base(published_at=iso(200)))
        self.assertEqual(r["verdict"], "过期")
        self.assertEqual(r["scarcity_score"], 0)

    def test_sales_zero_no_div_by_zero(self):
        r = score(base(want_count=10, sales_7d=0))
        self.assertEqual(r["w_supply_demand"], 1.0)

    def test_want_missing_default(self):
        r = score(base(want_count=None))
        self.assertEqual(r["w_supply_demand"], 0.8)

    def test_category_weights(self):
        self.assertEqual(score(base(category="球鞋"))["w_category"], 0.7)
        self.assertEqual(score(base(category="美妆"))["w_category"], 1.3)
        self.assertEqual(score(base(category="服饰"))["w_category"], 1.0)

    def test_category_prior_blend(self):
        # 账单先验：静态 1.3 与账单 1.4 取均值
        prior = {"美妆": {"factor": 1.4}}
        self.assertEqual(score(base(category="美妆"), prior=prior)["w_category"], 1.35)
        # 无先验类目退回静态分
        self.assertEqual(score(base(category="球鞋"), prior=prior)["w_category"], 0.7)

    def test_exposure_coeff_and_blacklist(self):
        # 无 first_seen（老数据）无曝光系数
        self.assertEqual(score(base(seen_count=0))["exposure_coeff"], 0.0)
        # 首发满3天=全网皆知（天数制，与爬取频率解耦）
        it5 = base(seen_count=0, first_seen=iso(5 * 24))
        self.assertEqual(score(it5)["exposure_coeff"], 1.0)
        # 首日曝光系数为 0（保护首发窗口之外的冷静期得分）
        self.assertEqual(score(base(seen_count=0, first_seen=iso(12)))["exposure_coeff"], 0.0)
        # 满3天 且 无 last_seen（平台下架/无证据） -> 黑名单
        r = score(base(seen_count=0, first_seen=iso(5 * 24)))
        self.assertEqual(r["verdict"], "黑名单")
        self.assertEqual(r["scarcity_score"], 0)

    def test_watch_verdict_keek(self):
        # v3.1: 首发满3天（热度已过）但仍在售(last_seen新鲜)且净利达标 -> 可蹲
        it = base(seen_count=0, first_seen=iso(5 * 24), last_seen=iso(5))
        r = score(it)
        self.assertEqual(r["verdict"], "可蹲")
        # 价格轨迹在跌 >=3% -> 可蹲·降价中
        hist = {"1": [["2026-08-20T10:00:00", 500.0, 300.0],
                      ["2026-08-27T10:00:00", 470.0, 300.0]]}
        it2 = dict(it, carry_id="1")
        r2 = score(it2, history=hist)
        self.assertEqual(r2["verdict"], "可蹲·降价中")
        self.assertAlmostEqual(r2["price_trend"]["pct"], -6.0, places=1)
        # 净利不达标的热款仍是黑名单
        r3 = score(base(du_price=320, cost=300, first_seen=iso(5 * 24), last_seen=iso(5)))
        self.assertEqual(r3["verdict"], "黑名单")

    def test_cold_pick_verdict(self):
        r = score(base())
        self.assertEqual(r["net_profit"], 130.0)
        self.assertEqual(r["verdict"], "冷门优选")

    def test_low_profit_not_ranked(self):
        it = base(du_price=300, cost=280)
        r = score(it)
        self.assertLess(r["net_profit"], 50)
        ranked = [x for x in [dict(it, **r)] if x["net_profit"] is not None and x["net_profit"] >= RATES["min_net_profit"]]
        self.assertEqual(ranked, [])

    def test_missing_publish_time(self):
        r = score(base(published_at=None))
        self.assertEqual(r["w_time"], 1.0)
        self.assertEqual(r["time_label"], "时效未知")

    def test_score_formula_exact(self):
        # seen_count 已废弃；曝光按 first_seen 天数：首日系数 0
        it = base(du_price=1851.5, cost=1349, want_count=None, seen_count=3, first_seen=iso(12))
        r = score(it)
        self.assertAlmostEqual(r["net_profit"], 283.84, places=2)
        self.assertEqual(r["scarcity_score"], round(283.84 * 1.0 * 0.8 * 1.0 * 1.0, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
