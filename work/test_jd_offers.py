import json
import os
import unittest
import copy
from unittest.mock import mock_open, patch
from datetime import datetime, timedelta
from jd_offers import reference_price, render_offers, validate_offer, render_dewu_comparison


class OfferRules(unittest.TestCase):
    def setUp(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'jd_offer_samples.json')
        with open(path, encoding='utf-8') as f:
            self.offer = json.load(f)[0]
        self.now = datetime.fromisoformat('2026-10-14T21:30:00+08:00')

    def render(self, offer, now=None):
        with patch('builtins.open', mock_open(read_data=json.dumps([offer]))):
            return render_offers('sample.json', now or self.now)

    def test_purchase_price_does_not_subtract_coupon_twice(self):
        self.assertEqual(reference_price({'wlprice':690, 'purchasePriceInfo':
                         {'purchasePrice':640, 'couponList':[{'discount':50}]}}), 640)

    def test_coupon_price_is_already_discounted(self):
        self.assertEqual(reference_price({'priceInfo':{'lowestCouponPrice':90,'lowestPrice':100}}),90)

    def test_no_manual_coupon_deduction_when_no_official_result(self):
        self.assertEqual(reference_price({'wlprice':100,'purchasePriceInfo':{'couponList':[{'discount':80}]}}),100)
        self.assertIsNone(reference_price({'wlprice':float('nan')}))

    def test_ambiguous_spec_or_unverified_links_rejected(self):
        for key, value in [('sku_id','opaque'),('item_url','https://item.jd.com/another.html'),('links_verified',False),('conditions','')]:
            bad = {**self.offer,key:value}
            self.assertIsNone(validate_offer(bad,self.now))

    def test_foreign_or_script_links_rejected(self):
        for link in ('javascript:alert(1)','https://jd.com.example.org/x','https://jd.com@evil.com/x'):
            self.assertIsNone(validate_offer({**self.offer,'coupon_url':link},self.now))

    def test_impossible_price_or_future_time_rejected(self):
        for key,value in [('reference_price',590),('basis_price',400),('captured_at','2027-01-01T00:00:00+08:00')]:
            self.assertIsNone(validate_offer({**self.offer,key:value},self.now))

    def test_stale_and_expired_offers_have_no_purchase_buttons(self):
        for now in (self.now + timedelta(days=2),self.now + timedelta(days=8)):
            page=self.render(self.offer,now)
            self.assertIn('历史券价',page)
            self.assertNotIn('href=',page)

    def test_ui_escapes_content_and_ignores_injected_net_profit(self):
        offer={**self.offer,'title':'<script>alert(1)</script>','net_profit':99999}
        page=self.render(offer)
        self.assertNotIn('<script>',page)
        self.assertIn('¥640.00',page)
        self.assertNotIn('99999',page)
        self.assertIn('① 领取优惠券',page)

    def test_dewu_income_is_separate_from_buyer_sales_and_cost(self):
        page = render_dewu_comparison(self.offer, datetime.fromisoformat('2026-10-15T15:00:00+08:00'))
        self.assertIn('¥321.33',page)
        self.assertIn('¥-297.31',page)
        self.assertIn('¥319.49',page)
        self.assertIn('¥-299.15',page)
        self.assertIn('可见 5 笔',page)
        self.assertIn('包装组合待核',page)
        self.assertIn('不是完整24小时或7天销量',page)

    def test_mixed_sku_capacity_or_income_tab_rejected(self):
        for key,value in [('jd_sku_id','999'),('capacity','230ml'),('income_tab_verified',False),('channel','立即变现')]:
            offer=copy.deepcopy(self.offer)
            offer['dewu_comparison'][key]=value
            self.assertNotIn('¥321.33',render_dewu_comparison(offer,datetime.fromisoformat('2026-10-15T15:00:00+08:00')))
        offer=copy.deepcopy(self.offer)
        offer['dewu_comparison']['recent_rows'][0]['capacity']='230ml'
        self.assertIn('待采样',render_dewu_comparison(offer,datetime.fromisoformat('2026-10-15T15:00:00+08:00')))

    def test_stale_dewu_samples_are_explicitly_historical(self):
        page=render_dewu_comparison(self.offer,datetime.fromisoformat('2026-10-17T15:00:00+08:00'))
        self.assertIn('历史对照',page)
        self.assertIn('相对时间以采样时为准',page)

    def test_future_dewu_capture_rejected(self):
        self.assertIn('待采样',render_dewu_comparison(self.offer,self.now))


if __name__ == '__main__':
    unittest.main()
