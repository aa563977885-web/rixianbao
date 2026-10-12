# -*- coding: utf-8 -*-
"""
核价回流：待核价清单(已填得物核价) -> data/pool.json
====================================================
把你在待核价清单里填的「得物核价」回写到候选池，下轮打分自动算净利、
排位、进今日机会/盯款雷达——联盟新券从此参与正式排序。

用法:
  python work/import_verified.py                       # 默认读 outputs/site/checklist.xlsx
  python work/import_verified.py --file 你核完的.xlsx
规则: 只回传 G列(得物核价)非空 的行；按 B列ID 匹配池子条目；
      同时把 E列购入日期 记入 data/purchase_log.json（提醒你誊账单）。
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

from openpyxl import load_workbook

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FILE = os.path.join(ROOT, "outputs", "site", "checklist.xlsx")
POOL = os.path.join(ROOT, "data", "pool.json")
PURCHASE_LOG = os.path.join(ROOT, "data", "purchase_log.json")
# 列布局见 export_tracker.HEADERS：B=ID, E=购入日期, G=得物核价, U=得物分享链接
COL_ID, COL_BUY_DATE, COL_VERIFY, COL_SHARE = "B", "E", "G", "U"
DATA_START = 5


def main():
    ap = argparse.ArgumentParser(description="核价回流")
    ap.add_argument("--file", default=DEFAULT_FILE)
    args = ap.parse_args()

    if not os.path.exists(args.file):
        print(f"找不到 {args.file}")
        return
    wb = load_workbook(args.file, data_only=True)
    ws = wb["试销追踪"]

    pool = json.load(open(POOL, encoding="utf-8"))
    pool_map = {str(d.get("carry_id")): d for d in pool if d.get("carry_id")}

    plog = json.load(open(PURCHASE_LOG, encoding="utf-8")) if os.path.exists(PURCHASE_LOG) else []

    updated, purchases, missing = [], [], []
    for r in range(DATA_START, ws.max_row + 1):
        cid = ws[f"{COL_ID}{r}"].value
        if cid is None or str(cid).strip() == "":
            continue
        cid = str(cid).strip()
        verify = ws[f"{COL_VERIFY}{r}"].value
        buy_date = ws[f"{COL_BUY_DATE}{r}"].value
        if verify is not None and str(verify).strip() != "":
            try:
                du = round(float(verify), 2)
            except (TypeError, ValueError):
                missing.append(f"{cid}: 核价值非数字 '{verify}'")
                continue
            if cid in pool_map:
                pool_map[cid]["du_price"] = du
                updated.append(f"{cid} {pool_map[cid].get('title', '')[:20]} -> 得物价{du}")
            else:
                missing.append(f"{cid}: 池子里没有该ID")
        elif cid in pool_map:
            # U 列分享链接回流：得物App「分享-复制链接」粘进来即可，spuId 自动抓价
            share = ws[f"{COL_SHARE}{r}"].value
            link = str(share or "").strip()
            m = re.search(r"spuId[=/](\d{5,12})", link)
            if m:
                # 落地页没有现货价（¥ 是发售价），只补元数据；得物价仍需 G 列手填
                spu = m.group(1)
                it = pool_map[cid]
                it["dewu_spu_id"] = spu
                try:
                    sys.path.insert(0, os.path.join(ROOT, "work"))
                    from dewu_price import fetch_spu
                    r2 = fetch_spu(spu)
                    if r2.get("article_no") and not it.get("article_no"):
                        it["article_no"] = r2["article_no"]
                    if r2.get("msrp"):
                        it["msrp"] = r2["msrp"]
                    updated.append(f"{cid} {it.get('title', '')[:18]} 已关联得物款（货号 {it.get('article_no') or '?'}，发售价 {r2.get('msrp') or '?'}）；得物价请填G列")
                except Exception as e:
                    print(f"[{cid}] 元数据抓取失败: {str(e)[:60]}（spu 已记下）")
            elif link and "dewu" not in link:
                missing.append(f"{cid}: U列不是得物链接？'{link[:40]}'")
        if buy_date is not None and str(buy_date).strip() != "":
            purchases.append({"id": cid, "title": pool_map.get(cid, {}).get("title", ""), "date": str(buy_date)})

    if purchases:
        known = {(p["id"], str(p["date"])) for p in plog}
        for p in purchases:
            if (p["id"], p["date"]) not in known:
                plog.append(p)

    with open(POOL, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)
    if plog:
        with open(PURCHASE_LOG, "w", encoding="utf-8") as f:
            json.dump(plog, f, ensure_ascii=False, indent=2)

    print(f"回传完成：核价回写 {len(updated)} 条 | 购入记录 {len(purchases)} 条")
    for u in updated:
        print("  ", u)
    for m in missing:
        print("  !", m)
    if not updated and not purchases:
        print("（没有可回传的行——G列得物核价都还是空的？）")
    print("下一步：跑 python work/scoring.py 让核价结果参与排序")


if __name__ == "__main__":
    main()
