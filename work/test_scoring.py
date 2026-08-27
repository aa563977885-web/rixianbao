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


class TestScoring(unittest.TestCase):
    def test_time_windows_4_branches(self):
        r = scoring.score_item(base(published_at=iso(6)), RATES, BOOST, CUT, now=NOW)
        self.assertEqual(r["w_time"], 0.5)
        self.assertEqual(r["time_label"], "首发窗口·避让")
        r = scoring.score_item(base(published_at=iso(30)), RATES, BOOST, CUT, now=NOW)
        self.assertEqual(r["w_time"], 1.0)
        self.assertEqual(r["time_label"], "冷静期中")
        r = scoring.score_item(base(published_at=iso(100)), RATES, BOOST, CUT, now=NOW)
        self.assertEqual(r["w_time"], 1.3)
        self.assertEqual(r["time_label"], "真需求确认")
        r = scoring.score_item(base(published_at=iso(200)), RATES, BOOST, CUT, now=NOW)
        self.assertEqual(r["verdict"], "过期")
        self.assertEqual(r["scarcity_score"], 0)

    def test_sales_zero_no_div_by_zero(self):
        r = scoring.score_item(base(want_count=10, sales_7d=0), RATES, BOOST, CUT, now=NOW)
        self.assertEqual(r["w_supply_demand"], 1.0)

    def test_want_missing_default(self):
        r = scoring.score_item(base(want_count=None), RATES, BOOST, CUT, now=NOW)
        self.assertEqual(r["w_supply_demand"], 0.8)

    def test_category_weights(self):
        self.assertEqual(scoring.score_item(base(category="球鞋"), RATES, BOOST, CUT, now=NOW)["w_category"], 0.7)
        self.assertEqual(scoring.score_item(base(category="美妆"), RATES, BOOST, CUT, now=NOW)["w_category"], 1.3)
        self.assertEqual(scoring.score_item(base(category="服饰"), RATES, BOOST, CUT, now=NOW)["w_category"], 1.0)

    def test_exposure_coeff_and_blacklist(self):
        self.assertEqual(scoring.score_item(base(seen_count=0), RATES, BOOST, CUT, now=NOW)["exposure_coeff"], 0.0)
        self.assertEqual(scoring.score_item(base(seen_count=5), RATES, BOOST, CUT, now=NOW)["exposure_coeff"], 0.5)
        r = scoring.score_item(base(seen_count=12), RATES, BOOST, CUT, now=NOW)
        self.assertEqual(r["verdict"], "黑名单")
        self.assertEqual(r["scarcity_score"], 0)

    def test_cold_pick_verdict(self):
        r = scoring.score_item(base(), RATES, BOOST, CUT, now=NOW)
        self.assertEqual(r["net_profit"], 130.0)
        self.assertEqual(r["verdict"], "冷门优选")

    def test_low_profit_not_ranked(self):
        it = base(du_price=300, cost=280)
        r = scoring.score_item(it, RATES, BOOST, CUT, now=NOW)
        self.assertLess(r["net_profit"], 50)
        ranked = [x for x in [dict(it, **r)] if x["net_profit"] is not None and x["net_profit"] >= RATES["min_net_profit"]]
        self.assertEqual(ranked, [])

    def test_missing_publish_time(self):
        r = scoring.score_item(base(published_at=None), RATES, BOOST, CUT, now=NOW)
        self.assertEqual(r["w_time"], 1.0)
        self.assertEqual(r["time_label"], "时效未知")

    def test_score_formula_exact(self):
        it = base(du_price=1851.5, cost=1349, want_count=None, seen_count=3)
        r = scoring.score_item(it, RATES, BOOST, CUT, now=NOW)
        self.assertAlmostEqual(r["net_profit"], 283.84, places=2)
        self.assertEqual(r["scarcity_score"], round(283.84 * 1.0 * 0.8 * 1.0 * 0.7, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
