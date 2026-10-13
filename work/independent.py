"""只接受联盟选品和独立核价；历史门道价格不会进入独立池。"""
import json
import math
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_QUOTE_HOURS = 24
SOURCES = {"jd", "tbk"}


def fresh(value, now):
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            return False
        return 0 <= (now - dt).total_seconds() <= MAX_QUOTE_HOURS * 3600
    except (ValueError, TypeError):
        return False


def number(value, allow_zero=False):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and (value >= 0 if allow_zero else value > 0))


def trusted_link(item):
    url = str(item.get("url") or "")
    parsed = urlparse(url)
    domains = ("jd.com", "jd.hk") if item.get("source") == "jd" else ("taobao.com", "tmall.com", "tb.cn")
    if parsed.scheme not in ("http", "https") or not any(
            parsed.hostname == d or (parsed.hostname or "").endswith("." + d) for d in domains):
        return ""
    if parsed.hostname == "item.jd.com" and not re.fullmatch(r"/\d+\.html", parsed.path):
        return ""  # 不能把不透明联盟 ID 拼成京东 SKU 链接
    return url


def quote_error(item, record, now):
    if not isinstance(record, dict):
        return "待核对同货号、颜色和尺码"
    supplier, dewu = record.get("supplier"), record.get("dewu")
    if not isinstance(supplier, dict) or not isinstance(dewu, dict):
        return "缺少货源或得物核价记录"
    for key in ("article_no", "color", "size"):
        a, b = str(supplier.get(key) or "").strip(), str(dewu.get(key) or "").strip()
        if not a or a != b:
            return "货源与得物的货号、颜色、尺码未完全匹配"
    if str(supplier.get("platform_item_id") or "") != str(item["carry_id"]).split("-", 1)[1]:
        return "核价记录不属于当前货源商品"
    if not number(supplier.get("cost")) or supplier["cost"] != item.get("cost"):
        return "货源价格已变化或没有核实"
    if not number(dewu.get("price")) or dewu.get("price_kind") not in ("buyer_quote", "seller_settlement"):
        return "只接受当前买家报价或卖家预计到手价，不接受起价、发售价和历史成交价"
    if not fresh(supplier.get("checked_at"), now) or not fresh(dewu.get("checked_at"), now):
        return "核价已超过24小时，或缺少有效核价时间"
    if not supplier.get("evidence") or not dewu.get("evidence"):
        return "缺少货源或得物核价依据"
    if dewu["price_kind"] == "seller_settlement" and not number(record.get("shipping_cost"), True):
        return "卖家到手价还需确认寄件成本"
    if not item.get("url"):
        return "货源链接待核实"
    return ""


def prepare_pool(pool, quotes, now=None):
    now = now or datetime.now(timezone.utc)
    records = {str(q.get("carry_id")): q for q in quotes if isinstance(q, dict)}
    out = []
    for original in pool:
        if original.get("source") not in SOURCES:
            continue
        item = dict(original)
        if not str(item.get("carry_id") or "").startswith(item["source"] + "-"):
            continue
        # 所有旧得物字段都重新从独立核价记录构建，禁止沿用相似标题匹配的价格。
        for key in ("du_price", "net_profit", "scarcity_score", "dewu_spu_id", "article_no",
                    "size", "color", "du_price_checked_at", "dewu_price_kind", "shipping_cost",
                    "linked_from", "linked_title", "link_score", "msrp", "want_count", "sales_7d"):
            item.pop(key, None)
        item["independent"] = True
        item["url"] = trusted_link(item)
        item["source_link_status"] = "可打开" if item["url"] else "待核实"
        item["du_price"] = None
        item["net_profit"] = None
        record = records.get(str(item["carry_id"]))
        error = quote_error(item, record, now)
        item["price_status"] = "待核价" if error else "已核价"
        item["verification_note"] = error
        if not error:
            supplier, dewu = record["supplier"], record["dewu"]
            for key in ("article_no", "color", "size"):
                item[key] = supplier[key]
            item["du_price"] = dewu["price"]
            item["dewu_price_kind"] = dewu["price_kind"]
            item["du_price_checked_at"] = dewu["checked_at"]
            item["quote_evidence"] = dewu["evidence"]
            item["shipping_cost"] = record.get("shipping_cost")
        out.append(item)
    return out


def main():
    path = os.path.join(ROOT, "data", "pool.json")
    with open(path, encoding="utf-8") as f:
        pool = json.load(f)
    quotes_path = os.path.join(ROOT, "data", "verified_quotes.json")
    quotes = []
    if os.path.exists(quotes_path):
        with open(quotes_path, encoding="utf-8") as f:
            quotes = json.load(f)
    own = prepare_pool(pool, quotes)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(own, f, ensure_ascii=False, indent=2)
    print(f"独立候选 {len(own)} 条；已核价 {sum(x['price_status'] == '已核价' for x in own)} 条；已排除非联盟来源")


if __name__ == "__main__":
    main()
