# -*- coding: utf-8 -*-
"""得物价自动刷新：对池子里带 dewu_spu_id 的条目，直接读得物分享落地页
（router/product/ProductDetail，任意浏览器放行）刷新 du_price。

优先级：无 du_price 的 > 得物价最久未刷新的；每轮上限 DEWU_REFRESH_LIMIT（默认 15，
playwright 单条约 10-20 秒）。门道爬虫负责补 spuId；联盟条目靠用户分享链接回流。
"""
import json
import os
import time
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys_path = os.path.join(ROOT, "work")
import sys
sys.path.insert(0, sys_path)

POOL = os.path.join(ROOT, "data", "pool.json")
LIMIT = int(os.environ.get("DEWU_REFRESH_LIMIT") or 15)
STALE_HOURS = 20  # 得物价超过 20 小时未核就重刷


def now_iso():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def load_pool():
    with open(POOL, encoding="utf-8") as f:
        return json.load(f)


def save_pool(pool):
    with open(POOL, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)


def checked_at(it):
    return it.get("du_price_checked_at") or ""


def main():
    from dewu_price import fetch_spu
    pool = load_pool()
    cands = [i for i in pool if i.get("dewu_spu_id")]
    if not cands:
        print("[dewu] 池内暂无带 spuId 的条目（门道爬虫首轮后会补上）")
        return
    stale = [i for i in cands if (not i.get("du_price")) or _age_hours(checked_at(i)) >= STALE_HOURS]
    stale.sort(key=lambda i: (i.get("du_price") is not None, checked_at(i)))
    batch = stale[:LIMIT]
    print(f"[dewu] 带spu {len(cands)} 条 | 待刷 {len(stale)} | 本轮刷 {len(batch)}")
    ok = 0
    for it in batch:
        r = fetch_spu(it["dewu_spu_id"])
        if r.get("price"):
            it["du_price"] = r["price"]
            it["du_price_checked_at"] = now_iso()
            if r.get("article_no") and not it.get("article_no"):
                it["article_no"] = r["article_no"]
            ok += 1
            print(f"  {it['dewu_spu_id']} {str(it.get('title'))[:26]} -> ¥{r['price']}")
        else:
            it["du_price_checked_at"] = now_iso()  # 失败也记时间，避免反复打无效页
            print(f"  {it['dewu_spu_id']} 无价格（可能被弹端）")
        time.sleep(2)
    save_pool(pool)
    print(f"[dewu] 刷新完成 {ok}/{len(batch)}")


def _age_hours(iso_str):
    if not iso_str:
        return 1e9
    try:
        dt = datetime.fromisoformat(iso_str)
        return (datetime.now(timezone(timedelta(hours=8))) - dt).total_seconds() / 3600
    except ValueError:
        return 1e9


if __name__ == "__main__":
    main()
