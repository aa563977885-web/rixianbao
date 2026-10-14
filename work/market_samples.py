"""Display independent market samples without promoting unmatched supply offers."""
import html
import json
import math
from datetime import datetime, timezone


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
                         '<p style="font-size:12px;line-height:1.7;color:#666">成交笔数仅来自采到的App展示记录，非全量销量；'
                         '“7天前”边界未计入。买家报价不等于卖家实收。<br>'
                         '同规格货源及实际费用待核实，尚不计算净利润。</p></section>')
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return '\n'.join(cards)
