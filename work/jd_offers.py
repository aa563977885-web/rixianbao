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


def render_dewu_comparison(offer, now):
    """同容量候选按包装分列；包装未完全确认时不输出净利润。"""
    e = lambda s: html.escape(str(s), quote=True)
    missing = '<p><strong>得物核价未完成：</strong>预计收入、同规格近期成交待采样；暂不计算收益。</p>'
    sample = offer.get('dewu_comparison')
    if not isinstance(sample, dict):
        return missing
    try:
        purchase = sample['purchase_sample']
        captured = datetime.fromisoformat(sample['captured_at'])
        purchased = datetime.fromisoformat(purchase['captured_at'])
        recent_at = datetime.fromisoformat(sample['recent_captured_at'])
        cost = positive(purchase['page_reference_price'])
        packages = ('无礼盒无礼袋', '官方礼盒无礼袋', '官方礼袋无礼盒', '官方礼盒礼袋')
        rows = sample['income_rows']
        if (sample['jd_sku_id'] != offer['sku_id'] or sample['source_kind'] != 'dewu_app_public_ui'
                or sample['article'] != '经典版神仙水' or sample['capacity'] != '75ml'
                or sample['channel'] != '普通发货' or sample['income_tab_verified'] is not True
                or sample['match_status'] != 'capacity_version_checked_package_pending'
                or purchase['item_url'] != offer['item_url'] or cost is None
                or any(t.tzinfo is None or t > now for t in (captured, purchased, recent_at))
                or len(rows) != 4 or {r['package'] for r in rows} != set(packages)
                or any(r['capacity'] != sample['capacity'] or positive(r['estimated_income']) is None for r in rows)):
            return missing
        sales = sample['recent_rows']
        for sale in sales:
            if (sale['capacity'] != sample['capacity'] or sale['package'] not in packages
                    or positive(sale['buyer_price']) is None
                    or not sale['displayed_time']):
                return missing
        stale = any((now-t).total_seconds() > 86400 for t in (captured, purchased, recent_at))
        state = '历史对照 · 请重新核价' if stale else '同容量版本已查 · 包装组合待核'
        body = ''.join(f'<tr><td>{e(r["package"])}</td><td>¥{float(r["estimated_income"]):.2f}</td>'
                       f'<td>¥{float(r["estimated_income"])-cost:+.2f}</td></tr>' for r in rows)
        recent = ''.join(f'<li>{e(s["capacity"])} {e(s["package"])}：买家成交价 ¥{float(s["buyer_price"]):.2f} · {e(s["displayed_time"])}</li>' for s in sales)
        negative = all(float(r['estimated_income']) < cost for r in rows)
        return (f'<section style="border-top:1px solid #ddd;margin-top:12px;padding-top:12px">'
                f'<strong>得物对照 · {e(sample["article"])} · {e(sample["capacity"])}</strong><p>{state}</p>'
                f'<p>京东当前页面参考价 <strong>¥{cost:.2f}</strong>（{purchased.astimezone(BJ).strftime("%m-%d %H:%M")}；未核实结算）</p>'
                '<table style="width:100%;text-align:left"><thead><tr><th>75ml 包装</th><th>普通发货预计收入</th><th>收入减参考采购价</th></tr></thead>'
                f'<tbody>{body}</tbody></table><p><strong>{"当前采样价差全部为负" if negative else "候选价差待核"}</strong>；'
                '京东为经典红盒，礼袋、条码、效期及得物收货要求仍待实物确认。表内各包装独立报价，不代表全部都能匹配采购商品。</p>'
                f'<details open><summary>近期成交样本 · 礼盒两种包装可见 {len(sales)} 笔</summary><ul>{recent}</ul></details>'
                f'<p style="font-size:12px;color:#666">成交采样 {recent_at.astimezone(BJ).strftime("%m-%d %H:%M")}；'
                '相对时间以采样时为准。仅为可见记录下限，不是完整24小时或7天销量；53万+是商品累计展示，未用来计算动销。'
                f'收入采样 {captured.astimezone(BJ).strftime("%m-%d %H:%M")}；App预计值不是已到账金额。'
                '费用明细未读取，不重复扣猜测平台费；寄件等额外成本未计，不计算最终净利润。当前为人工触发采样。</p></section>')
    except (KeyError, TypeError, ValueError):
        return missing


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
                     f'<strong>京东优惠与得物核价 · {e(offer["title"])}</strong>'
                     f'<p>{e(status)}</p><p>联盟参考到手价 <strong style="color:#d94a25;font-size:20px">¥{offer["reference_price"]:.2f}</strong>'
                     f' · 基准价 ¥{offer["basis_price"]:.2f} − 券 ¥{offer["coupon_discount"]:.2f}</p>'
                     f'<p>满 {e(offer["coupon_threshold"])} 元减 {e(offer["coupon_discount"])} 元；券日期 '
                     f'{e(offer["coupon_start_date"])} 至 {e(offer["coupon_end_date"])}</p>'
                     f'<p>{e(offer["conditions"])}</p>{actions}{render_dewu_comparison(offer, now)}'
                     f'<p style="font-size:11px;color:#888">采样：{offer["captured"].astimezone(BJ).strftime("%m-%d %H:%M")}；'
                     '联盟券价随活动、账号和地区变化，以结算页为准。佣金另列，不抵扣采购价。</p></article>')
    if not cards:
        return ''
    return ('<details class="fold" style="margin:12px 0" open><summary>🎟 京东活动优惠 · 已采样入口</summary>'
            '<p style="font-size:12px;color:#666">从京东联盟商品页直接核对券价和入口。当前为网页采样，尚未接通活动池定时采集；不保证全网最低价。</p>'
            + ''.join(cards) + '</details>')
