"""京东官方优惠采样；参考价不代替账号结算价，不从到手价再次减券。"""
import html
import json
import math
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

BJ = timezone(timedelta(hours=8))


def positive(value):
    if isinstance(value, bool):
        return None
    try:
        amount = float(value)
        return amount if math.isfinite(amount) and amount > 0 else None
    except (TypeError, ValueError):
        return None


def reference_price(goods):
    """官方 purchasePrice 和 lowestCouponPrice 已含优惠，不能二次减券。"""
    purchase = goods.get('purchasePriceInfo') or {}
    prices = goods.get('priceInfo') or {}
    for value in (purchase.get('purchasePrice'), prices.get('lowestCouponPrice'),
                  prices.get('lowestPrice'), goods.get('wlprice'), prices.get('price')):
        amount = positive(value)
        if amount is not None:
            return amount
    return None


def official_link(value):
    if not isinstance(value, str):
        return ''
    parsed = urlparse(value)
    if (parsed.scheme != 'https' or parsed.username or parsed.password
            or parsed.port not in (None, 443)):
        return ''
    host = parsed.hostname or ''
    return value if host == 'jd.com' or host.endswith('.jd.com') else ''


def validate_offer(offer, now):
    """只显示有明确 SKU、实测入口及券价算式的采样；旧采样关闭入口。"""
    if not isinstance(offer, dict) or offer.get('source_kind') != 'jd_union_public_ui':
        return None
    try:
        sku = str(offer['sku_id'])
        captured = datetime.fromisoformat(offer['captured_at'])
        start, end = date.fromisoformat(offer['coupon_start_date']), date.fromisoformat(offer['coupon_end_date'])
        basis, price, discount, threshold = [positive(offer.get(k)) for k in
            ('basis_price', 'reference_price', 'coupon_discount', 'coupon_threshold')]
        if (not sku.isdigit() or offer['item_url'] != f'https://item.jd.com/{sku}.html'
                or captured.tzinfo is None or captured > now or start > end
                or any(x is None for x in (basis, price, discount, threshold))
                or basis < threshold or abs(basis - discount - price) > 0.011
                or offer.get('links_verified') is not True
                or not offer.get('conditions') or not offer.get('title')
                or not official_link(offer.get('coupon_url'))
                or not official_link(offer.get('promotion_url'))):
            return None
        today = now.astimezone(BJ).date()
        active = start <= today <= end and (now - captured).total_seconds() <= 86400
        return {**offer, 'active': active, 'captured': captured,
                'reference_price': price, 'basis_price': basis, 'coupon_discount': discount}
    except (KeyError, TypeError, ValueError):
        return None


def render_offers(path, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, list):
            return ''
    except (OSError, ValueError):
        return ''
    cards = []
    e = lambda s: html.escape(str(s), quote=True)
    for raw in data:
        offer = validate_offer(raw, now)
        if not offer:
            continue
        status = '券价与入口已采样 · 结算待核实' if offer['active'] else '历史券价 · 请重新核实'
        actions = ''
        if offer['active']:
            actions = (f'<p><a class="buy" href="{e(offer["coupon_url"])}" target="_blank" rel="noopener">① 领取优惠券</a> '
                       f'<a class="buy" href="{e(offer["promotion_url"])}" target="_blank" rel="noopener">② 打开推广购买链接</a></p>')
        cards.append(f'<article class="card" style="border:2px solid #df9a32">'
                     f'<strong>京东优惠实测 · {e(offer["title"])}</strong>'
                     f'<p>{e(status)}</p><p>联盟参考到手价 <strong style="color:#d94a25;font-size:20px">¥{offer["reference_price"]:.2f}</strong>'
                     f' · 基准价 ¥{offer["basis_price"]:.2f} − 券 ¥{offer["coupon_discount"]:.2f}</p>'
                     f'<p>满 {e(offer["coupon_threshold"])} 元减 {e(offer["coupon_discount"])} 元；券日期 '
                     f'{e(offer["coupon_start_date"])} 至 {e(offer["coupon_end_date"])}</p>'
                     f'<p>{e(offer["conditions"])}</p>{actions}'
                     f'<p style="font-size:11px;color:#888">采样：{offer["captured"].astimezone(BJ).strftime("%m-%d %H:%M")}；'
                     '价格随活动、账号和地区变化，以结算页为准。佣金另列，不抵扣采购价。得物同款尚未匹配。</p></article>')
    if not cards:
        return ''
    return ('<details class="fold" style="margin:12px 0" open><summary>🎟 京东活动优惠 · 已采样入口</summary>'
            '<p style="font-size:12px;color:#666">从京东联盟商品页直接核对券价和入口。当前为网页采样，尚未接通活动池定时采集；不保证全网最低价。</p>'
            + ''.join(cards) + '</details>')
