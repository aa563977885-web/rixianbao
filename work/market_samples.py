"""Display independent market samples without promoting unmatched supply offers."""
import html
import json
import math
import re
from datetime import datetime, timezone


def validated_income(sample, now):
    income = sample.get('income_sample')
    if not isinstance(income, dict):
        return {}, None
    try:
        if any(not sample.get(k) or income.get(k) != sample[k] for k in ('article_no', 'color', 'gender')):
            return {}, None
        if (income.get('price_kind') != 'app_estimated_income' or income.get('channel') != '普通发货'
                or income.get('tab_verified') is not True):
            return {}, None
        captured = datetime.fromisoformat(income['captured_at'])
        if captured.tzinfo is None or captured > now:
            return {}, None
        prices = {}
        for row in income['records']:
            size, amount = row['size'], row['estimated_income']
            if (not isinstance(size, str) or size in prices or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', size)
                    or not isinstance(amount, (int, float)) or isinstance(amount, bool)
                    or not math.isfinite(amount) or amount < 0):
                return {}, None
            prices[size] = amount
        return prices, captured
    except (KeyError, TypeError, ValueError, OverflowError):
        return {}, None


def render_income(sample, now):
    prices, captured = validated_income(sample, now)
    if not prices:
        return ''
    status = '预计收入采样' if (now - captured).total_seconds() <= 86400 else '历史预计收入（超过24小时，需重新核价）'
    rows = ''.join(f'<tr><td>{html.escape(size)}</td><td>¥{amount:.2f}</td></tr>' for size, amount in prices.items())
    return ('<details open><summary>普通发货 · ' + status + '</summary><table class="info">'
            '<tr><th>尺码</th><th>得物App预计收入</th></tr>' + rows + '</table></details>'
            '<p style="font-size:12px;color:#666">收入采样：' + html.escape(captured.isoformat()) + '。'
            '这是出售面板显示的预估值，不是已到账金额；费用明细尚未读取，不重复扣除估算平台费。</p>')


def render_supplier(sample, when, now):
    """Compare checked identities, never turn displayed prices into net profit."""
    supplier = sample.get('supplier')
    if not isinstance(supplier, dict):
        return ''
    try:
        for key in ('article_no', 'color', 'gender'):
            if not sample.get(key) or supplier.get(key) != sample[key]:
                return ''
        captured = datetime.fromisoformat(supplier['captured_at'])
        if captured.tzinfo is None or captured > now or supplier.get('cost_kind') != 'displayed_to_hand_price':
            return ''
        e = lambda value: html.escape(str(value), quote=True)
        quotes = {q['size']: q['buyer_quote'] for q in sample['quotes']}
        if len(quotes) != len(sample['quotes']):
            return ''
        offers = supplier.get('offers', [])
        sizes = [o.get('size') for o in offers]
        if len(set(sizes)) != len(sizes):
            return ''
        rows, gaps = [], []
        income_prices, income_when = validated_income(sample, now)
        income_rows = []
        for offer in offers:
            size, cost = offer.get('size'), offer.get('displayed_cost')
            item_id = offer.get('platform_item_id')
            if (size not in quotes or not isinstance(cost, (int, float)) or isinstance(cost, bool)
                    or not math.isfinite(cost) or cost <= 0 or not isinstance(item_id, str)
                    or not re.fullmatch(r'[0-9]+', item_id)
                    or offer.get('url') != f'https://item.jd.com/{item_id}.html'):
                continue
            gap = round(quotes[size] - cost, 2)
            gaps.append(gap)
            if size in income_prices:
                amount = income_prices[size]
                income_rows.append(f'<tr><td>{e(size)}</td><td>¥{amount:.2f}</td>'
                                   f'<td>¥{cost:.2f}</td><td>¥{amount - cost:+.2f}</td></tr>')
            rows.append(f'<tr><td>{e(size)}</td><td><a href="{e(offer["url"])}" target="_blank" '
                        f'rel="noopener noreferrer">¥{cost:.2f}</a></td>'
                        f'<td>¥{quotes[size]:.2f}</td><td>¥{gap:+.2f}</td></tr>')
        if not rows:
            return ''
        old = any((now - t).total_seconds() > 86400 for t in (when, captured))
        status = '历史价格对照（超过24小时，需重新核价）' if old else (
            '当前采样无正价差' if max(gaps) <= 0 else '存在正价差，结算及费用待核实')
        income_comparison = ''
        if income_rows:
            historical = any((now - t).total_seconds() > 86400 for t in (captured, income_when))
            income_comparison = ('<p><strong>' + ('历史收入对照（需重新核价）' if historical else '预计收入与采购价对照') + '</strong></p>'
                                 '<table class="info"><tr><th>尺码</th><th>App预计收入</th><th>京东页面价</th>'
                                 '<th>收入减采购价</th></tr>' + ''.join(income_rows) + '</table>'
                                 '<p style="font-size:12px;color:#666">收入减采购价未扣寄件等额外费用，'
                                 '未计入联盟佣金和京豆返还，不代表最终净利润。</p>')
        return (income_comparison + '<p><strong>' + status + '</strong> · ' + e(supplier.get('shop', '京东货源')) + '</p>'
                '<table class="info"><tr><th>尺码</th><th>京东页面价</th><th>得物买家报价</th>'
                '<th>费用前价差</th></tr>' + ''.join(rows) + '</table>'
                '<p style="font-size:12px;color:#666">货源采样：' + e(captured.isoformat()) + '。'
                '京东价格受账号、优惠及配送地区影响；未核实最终结算价和下单库存。'
                '京豆返还未抵扣成本。费用前价差不等于净利润。</p>')
    except (KeyError, TypeError, ValueError, OverflowError):
        return ''


def render_samples(path, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        with open(path, encoding='utf-8') as f:
            samples = json.load(f)
    except (FileNotFoundError, ValueError):
        return ''
    if not isinstance(samples, list):
        return ''
    cards = []
    for sample in samples:
        try:
            when = datetime.fromisoformat(sample['quote_captured_at'])
            if when.tzinfo is None or when > now:
                continue
            quotes = sample['quotes']
            if not quotes or sample['quote_kind'] != 'buyer_quote':
                continue
            if any(not isinstance(q['buyer_quote'], (int, float)) or isinstance(q['buyer_quote'], bool)
                   or not math.isfinite(q['buyer_quote']) or q['buyer_quote'] <= 0 for q in quotes):
                continue
            e = lambda value: html.escape(str(value))
            freshness = '采样快照' if (now - when).total_seconds() <= 86400 else '历史采样（超过24小时，需重新核价）'
            quote_rows = ''.join(f'<tr><td>{e(q["size"])}</td><td>¥{q["buyer_quote"]:g}</td></tr>' for q in quotes)
            supplier_html = render_supplier(sample, when, now)
            sales_rows = []
            for sale in sample.get('sales', []):
                count = sale.get('observed_within_7d')
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    continue
                sales_rows.append(f'<tr><td>{e(sale["size"])}</td><td>7天内可见至少 {count} 笔</td></tr>')
            cards.append('<section class="card" style="border:2px solid #10a6ad;margin-top:14px">'
                         '<div class="name">得物实测 · ' + e(sample['article_no']) + '</div>'
                         '<p style="font-size:13px;line-height:1.8;margin:8px 0">' + e(sample['title']) +
                         ' · ' + e(sample['color']) + ' · ' + e(sample.get('gender', '')) + '<br>' +
                         e(freshness) + ' · ' + e(when.isoformat()) + '</p>'
                         '<details><summary>各尺码买家报价</summary><table class="info">' + quote_rows + '</table></details>'
                         '<table class="info">' + ''.join(sales_rows) + '</table>'
                         + render_income(sample, now)
                         + supplier_html +
                         '<p style="font-size:12px;line-height:1.7;color:#666">成交笔数仅来自采到的App展示记录，非全量销量；'
                         '“7天前”边界未计入。买家报价不等于卖家实收。<br>'
                         + ('卖家结算及实际费用待核实，尚不计算净利润。' if supplier_html else
                            '同规格货源及实际费用待核实，尚不计算净利润。') + '</p></section>')
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return '\n'.join(cards)
