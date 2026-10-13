import copy
import unittest
import importlib.util
import os
import sys
import types
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from independent import prepare_pool


class IndependentTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.item = {"carry_id": "jd-123", "source": "jd", "cost": 100,
                     "url": "https://item.jd.com/123.html", "du_price": 999}
        spec = {"article_no": "GK9032", "color": "黑色", "size": "L",
                "checked_at": self.now.isoformat(), "evidence": "核价截图"}
        self.quote = {"carry_id": "jd-123", "supplier": dict(spec, platform_item_id="123", cost=100),
                      "dewu": dict(spec, price=280, price_kind="buyer_quote")}

    def test_legacy_data_cannot_be_relabelled_as_independent(self):
        legacy = dict(self.item, source="mendao", carry_id="456")
        out = prepare_pool([legacy, self.item], [], self.now)
        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0]["du_price"])

    def test_exact_fresh_quote_can_be_used(self):
        out = prepare_pool([self.item], [self.quote], self.now)[0]
        self.assertEqual(out["price_status"], "已核价")
        self.assertEqual((out["du_price"], out["size"]), (280, "L"))

    def test_mismatch_stale_price_kind_cost_and_link_are_rejected(self):
        mutations = [
            lambda q: q["dewu"].update(size="M"),
            lambda q: q["dewu"].update(price_kind="recent_purchase"),
            lambda q: q["dewu"].update(checked_at=(self.now - timedelta(hours=25)).isoformat()),
            lambda q: q["supplier"].update(cost=99),
            lambda q: q["dewu"].update(price=float("nan")),
            lambda q: q["supplier"].update(platform_item_id="456"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                quote = copy.deepcopy(self.quote)
                mutate(quote)
                self.assertIsNone(prepare_pool([self.item], [quote], self.now)[0]["du_price"])
        item = dict(self.item, url="https://item.jd.com/opaque_id.html")
        self.assertEqual(prepare_pool([item], [self.quote], self.now)[0]["url"], "")

    def test_settlement_does_not_double_deduct_platform_fees(self):
        from scoring import compute_net
        self.quote["dewu"]["price_kind"] = "seller_settlement"
        self.quote["shipping_cost"] = 8
        item = prepare_pool([self.item], [self.quote], self.now)[0]
        self.assertEqual(compute_net(item, {"category_rates": {}, "transfer_rate": .01, "fixed_fee": 15}), 172)

    def test_opaque_alliance_ids_do_not_create_fake_sku_links(self):
        path = os.path.join(os.path.dirname(__file__), "jd_client.py")
        spec = importlib.util.spec_from_file_location("jd_client_link_test", path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"requests": types.ModuleType("requests")}):
            spec.loader.exec_module(module)
        self.assertEqual(module.landing_url({}, "opaque_id"), "")
        self.assertEqual(module.landing_url({}, "123"), "https://item.jd.com/123.html")
        self.assertEqual(module.landing_url({"materialUrl": "https://item.jd.com/123.html"}, "opaque_id"),
                         "https://item.jd.com/123.html")


if __name__ == "__main__":
    unittest.main()
