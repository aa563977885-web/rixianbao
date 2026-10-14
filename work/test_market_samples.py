import json
from io import StringIO
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from market_samples import render_samples

class MarketSamplesTest(unittest.TestCase):
    def supplier(self, **overrides):
        supplier = {'article_no': '237153-BKGY', 'color': '黑灰', 'gender': '男款',
                    'captured_at': '2026-10-14T18:30:00+08:00',
                    'cost_kind': 'displayed_to_hand_price',
                    'offers': [{'size': '42.5', 'displayed_cost': 307.13,
                                'platform_item_id': '10183025767573',
                                'url': 'https://item.jd.com/10183025767573.html'}]}
        supplier.update(overrides)
        return supplier

    def render(self, captured='2026-10-14T18:00:00+08:00', price=236, supplier=None):
        sample = {'article_no': '237153-BKGY', 'title': '<shoe>', 'color': '黑灰',
                  'quote_kind': 'buyer_quote', 'quote_captured_at': captured,
                  'quotes': [{'size': '42.5', 'buyer_quote': price}],
                  'gender': '男款', 'supplier': supplier,
                  'sales': [{'size': '42.5', 'observed_within_7d': 11}]}
        with patch('builtins.open', return_value=StringIO(json.dumps([sample]))):
            return render_samples('samples.json', datetime(2026, 10, 14, 11, tzinfo=timezone.utc))

    def test_sample_is_escaped_and_not_presented_as_profit(self):
        result = self.render()
        self.assertIn('&lt;shoe&gt;', result)
        self.assertIn('非全量销量', result)
        self.assertIn('尚不计算净利润', result)
        self.assertIn('至少 11 笔', result)

    def test_old_quotes_are_labelled_and_invalid_or_future_quotes_rejected(self):
        self.assertIn('超过24小时', self.render('2026-10-12T18:00:00+08:00'))
        self.assertEqual('', self.render('2026-10-15T18:00:00+08:00'))
        self.assertEqual('', self.render(price=float('nan')))
        self.assertEqual('', self.render('2026-10-14T18:00:00'))

    def test_negative_spread_is_recomputed_and_not_net_profit(self):
        result = self.render(supplier=self.supplier(net_profit=9999))
        self.assertIn('¥-71.13', result)
        self.assertIn('当前采样无正价差', result)
        self.assertIn('尚不计算净利润', result)
        self.assertNotIn('9999', result)

    def test_supplier_identity_mismatch_is_not_compared(self):
        for key, value in [('article_no', 'other'), ('color', '白'), ('gender', '女款')]:
            with self.subTest(key=key):
                self.assertNotIn('费用前价差', self.render(supplier=self.supplier(**{key: value})))

    def test_untrusted_link_unmatched_size_and_invalid_cost_are_not_compared(self):
        for field, value in [('url', 'javascript:alert(1)'), ('size', '41'),
                             ('platform_item_id', 'other'), ('displayed_cost', float('nan')),
                             ('displayed_cost', True), ('displayed_cost', -1)]:
            supplier = self.supplier()
            supplier['offers'][0][field] = value
            with self.subTest(field=field, value=value):
                self.assertNotIn('费用前价差', self.render(supplier=supplier))

    def test_stale_or_future_supplier_cannot_claim_current_gap(self):
        result = self.render(supplier=self.supplier(captured_at='2026-10-12T18:00:00+08:00'))
        self.assertIn('历史价格对照', result)
        self.assertNotIn('当前采样无正价差', result)
        for captured in ['2026-10-15T18:00:00+08:00', '2026-10-14T18:00:00']:
            self.assertNotIn('费用前价差', self.render(supplier=self.supplier(captured_at=captured)))

    def test_positive_gap_still_requires_settlement_and_fees(self):
        result = self.render(price=350, supplier=self.supplier())
        self.assertIn('¥+42.87', result)
        self.assertIn('结算及费用待核实', result)
        self.assertIn('尚不计算净利润', result)
