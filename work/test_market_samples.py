import json
from io import StringIO
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from market_samples import render_samples

class MarketSamplesTest(unittest.TestCase):
    def render(self, captured='2026-10-14T18:00:00+08:00', price=236):
        sample = {'article_no': '237153-BKGY', 'title': '<shoe>', 'color': '黑灰',
                  'quote_kind': 'buyer_quote', 'quote_captured_at': captured,
                  'quotes': [{'size': '42.5', 'buyer_quote': price}],
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
