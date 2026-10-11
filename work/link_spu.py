# -*- coding: utf-8 -*-
"""联盟商品 ↔ 门道商机 标题匹配，借用 spuId 让得物价自动联动。

原理：门道池条目自带 dewu_spu_id（爬虫从 carryInfo 提取）。联盟条目只有营销化标题。
对每个联盟条目找标题最接近的门道条目 → 借用其 spuId → 得物详情页抓价，
并用详情页返回的商品名做反向校验（token 重叠率达标才写入，防误配）。

限制每轮 DEWU_LINK_LIMIT 条（默认 12），fetch_spu 单条约 10-20 秒。
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "work"))

POOL = os.path.join(ROOT, "data", "pool.json")
LIMIT = int(os.environ.get("DEWU_LINK_LIMIT") or 12)

STOP = re.compile(r"【[^】]*】|\[[^\]]*\]|（[^）]*）|\([^\)]*\)|男女|新款|正品|旗舰|官方|包邮|特价|"
                  r"促销|限量|正品保障|送女友|送礼|节日|舒适|百搭|透气|休闲|运动|潮流|时尚|经典|"
                  r"202[3-6]|男款|女款|男士|女士|\d+(\.\d)?(cm|ml|g|kg|ml)\b|\b[0-9]{2,4}\b", re.I)


def core_tokens(title):
    """标题 → 核心词集（去营销词/颜色标/规格）。"""
    t = STOP.sub(" ", str(title or ""))
    return {w for w in re.split(r"[\s/]+", t.lower()) if len(w) >= 2}


BRANDS = {"adidas", "阿迪达斯", "nike", "耐克", "puma", "彪马", "converse", "匡威", "vans", "万斯",
          "jordan", "aj", "new", "balance", "asics", "skechers", "李宁", "安踏", "fila", "斐乐"}


def model_tokens(title):
    """型号词：大写英文型号（D-PAD/ENTRAP/COURT）+ 数字货号，是同款的强信号。"""
    t = str(title or "").upper()
    toks = set(re.findall(r"[A-Z][A-Z0-9-]{2,}", t))
    return {x for x in toks if x.lower() not in BRANDS and x not in ("PRO", "MAX", "PLUS", "OFFICIAL", "COM")}


def similarity(a, b):
    ta, tb = core_tokens(a), core_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def main():
    from dewu_price import fetch_spu
    pool = json.load(open(POOL, encoding="utf-8"))
    donors = [i for i in pool if i.get("dewu_spu_id")]
    takers = [i for i in pool if i.get("source") in ("tbk", "jd") and not i.get("dewu_spu_id")]
    if not donors or not takers:
        print(f"[link] donors={len(donors)} takers={len(takers)}，无需匹配")
        return
    print(f"[link] 门道供体 {len(donors)} | 联盟待匹配 {len(takers)}")

    # 预排序：每个联盟条目取相似度最高的门道条目
    pairs = []
    for t in takers:
        tm = model_tokens(t.get("title"))
        if not tm:
            continue  # 无型号词的通用款（京东特供）得物上多无同款，不硬配
        best, bs = None, 0.0
        for d in donors:
            dm = model_tokens(d.get("title"))
            if not (tm & dm):
                continue  # 型号词无交集直接淘汰
            s = similarity(t.get("title"), d.get("title"))
            if s > bs:
                best, bs = d, s
        if best and bs >= 0.4:  # 型号词命中 + 核心词重叠过四成才抓价
            pairs.append((t, best, bs))
    pairs.sort(key=lambda x: -x[2])
    pairs = pairs[:LIMIT]
    print(f"[link] 预筛通过 {len(pairs)} 对（阈值0.5）")

    ok = 0
    for t, d, s in pairs:
        spu = d["dewu_spu_id"]
        try:
            r = fetch_spu(spu)
        except Exception as e:
            print(f"  [link] {t['carry_id']} 抓价异常 {str(e)[:50]}")
            continue
        # 反向校验：详情页商品名 vs 联盟标题
        name_sim = similarity(r.get("name") or "", t.get("title") or "")
        if r.get("price") and name_sim >= 0.5:
            t["dewu_spu_id"] = spu
            t["du_price"] = r["price"]
            t["du_price_checked_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
            if r.get("article_no") and not t.get("article_no"):
                t["article_no"] = r["article_no"]
            ok += 1
            print(f"  ✓ {str(t.get('title'))[:28]} ← spu {spu} ¥{r['price']}（词叠{s:.2f}/名校验{name_sim:.2f}）")
        else:
            print(f"  ✗ {str(t.get('title'))[:28]} 校验不过（名校验{name_sim:.2f}，spu {spu}）")
        time.sleep(2)

    json.dump(pool, open(POOL, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[link] 匹配写入 {ok}/{len(pairs)}")


if __name__ == "__main__":
    main()
