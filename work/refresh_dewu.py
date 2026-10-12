# -*- coding: utf-8 -*-
"""得物元数据刷新：对池子里带 dewu_spu_id 的条目读分享落地页，
只补 article_no（主货号）与 msrp（官方发售价），**不写 du_price**
（落地页的 ¥ 是发售价不是现货价；现货价以门道爬虫最低价为准）。

发售价的用途：卡片「官方发售价」行（现货 < 发售 = 折扣转卖，需求弱；
现货 > 发售 = 溢价款，稀缺信号）。每轮 DEWU_REFRESH_LIMIT 条，优先补缺货号的。
"""
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "work"))

POOL = os.path.join(ROOT, "data", "pool.json")
LIMIT = int(os.environ.get("DEWU_REFRESH_LIMIT") or 10)


def main():
    from dewu_price import fetch_spu
    pool = json.load(open(POOL, encoding="utf-8"))
    cands = [i for i in pool if i.get("dewu_spu_id")]
    # 优先：没有货号的 > 没有发售价的 > 最久没补的
    todo = [i for i in cands if not i.get("article_no")]
    todo += [i for i in cands if i.get("article_no") and not i.get("msrp")]
    batch = todo[:LIMIT]
    if not batch:
        print(f"[dewu] 带spu {len(cands)} 条，元数据齐全，本轮无需补")
        return
    print(f"[dewu] 待补元数据 {len(todo)} | 本轮 {len(batch)}")
    ok = 0
    for it in batch:
        r = fetch_spu(it["dewu_spu_id"])
        changed = False
        if r.get("article_no") and not it.get("article_no"):
            it["article_no"] = r["article_no"]
            changed = True
        if r.get("msrp") and not it.get("msrp"):
            it["msrp"] = r["msrp"]
            changed = True
        if r.get("name") and not it.get("dewu_name"):
            it["dewu_name"] = r["name"]
            changed = True
        if changed:
            ok += 1
            print(f"  {it['dewu_spu_id']} {str(it.get('title'))[:24]} 货号={r.get('article_no')} 发售价={r.get('msrp')}")
        time.sleep(2)
    with open(POOL, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)
    print(f"[dewu] 元数据补齐 {ok}/{len(batch)}")


if __name__ == "__main__":
    main()
