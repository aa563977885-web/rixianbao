# -*- coding: utf-8 -*-
"""
账单先验生成器：《得物 账单.xlsx》 -> config/ledger_prior.json
==============================================================
用你自己账单里的真实盈利数据，给打分器的类目因子供分（全网独一份的信息差）。

每类目的分数由「单均资金利润率」（单均净利 / 单均买入成本）分档：
  >=25% -> 1.4   15~25% -> 1.25   8~15% -> 1.0   <8% -> 0.75
类目样本数 <3 时不出分（避免一两单定调）。

用法:
  python work/ledger_prior.py                        # 默认读桌面账单
  python work/ledger_prior.py --bill "路径.xlsx"
账单更新后重跑一次即可，scored 下轮运行自动生效。
"""
import argparse
import json
import os
from datetime import datetime

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "config", "ledger_prior.json")
DEFAULT_BILL = os.path.join(os.path.expanduser("~"), "Desktop", "得物 账单.xlsx")

# 规则按顺序匹配，先具体后一般（“眼镜/度数”必须在“香水”之前拦住 VERSACE眼镜）
CATEGORY_RULES = [
    (["眼镜", "度数", "太阳镜", "墨镜"], "配饰"),
    (["帽子", "手链", "项链", "戒指", "饰品"], "配饰"),
    (["香水", "大地", "旷野", "木质香", "圆舞曲", "英国梨", "蓝风铃", "玉龙茶香",
      "祖玛珑", "Byredo", "罗意威", "爱马仕", "迪奥", "博柏利", "BURBERRY", "旷野"], "香水"),
    (["气垫", "遮瑕", "粉底", "口红", "精华", "面霜", "面膜", "护肤", "洁面", "唇釉",
      "腮红", "爱敬", "KRYOLAN", "科颜氏", "海蓝之谜", "娇韵诗", "精粹水"], "美妆"),
    (["鞋", "AF1", "Dunk", "板鞋", "跑鞋", "Gazelle", "Superstar", "CAMPUS"], "球鞋"),
    (["背包", "斜挎包", "双肩包", "托特", "手提包", "OSPREY", "帐篷", "冲锋衣"], "户外"),
    (["耳机", "AirPods", "手环", "手机", "平板", "充电宝", "音箱"], "数码"),
    (["衣", "裤", "外套", "卫衣", "羽绒", "裙", "衬衫", "家居服", "长袖", "短袖", "维密"], "服饰"),
]


def classify(name):
    t = str(name or "")
    for kws, cat in CATEGORY_RULES:
        if any(k in t for k in kws):
            return cat
    return "其他"


def bucket(roi):
    if roi is None:
        return None
    if roi >= 0.25:
        return 1.4
    if roi >= 0.15:
        return 1.25
    if roi >= 0.08:
        return 1.0
    return 0.75


def main():
    ap = argparse.ArgumentParser(description="账单先验生成器")
    ap.add_argument("--bill", default=DEFAULT_BILL, help="得物账单 xlsx 路径")
    ap.add_argument("--min-samples", type=int, default=3, help="类目最少样本数")
    args = ap.parse_args()

    df = pd.read_excel(args.bill, sheet_name="账单详情")
    df = df.dropna(how="all").loc[lambda d: d["货名"].notna()]
    for c in ("买入", "数量", "收入"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    sold = df[df["收入"].notna()].copy()
    sold["category"] = sold["货名"].map(classify)
    sold["cost"] = sold["买入"] * sold["数量"].fillna(1)
    sold["roi"] = sold["收入"] / sold["cost"]

    prior, log = {}, []
    for cat, g in sold.groupby("category"):
        if len(g) < args.min_samples:
            log.append(f"  {cat}: 样本{len(g)}条 <{args.min_samples}，不出分")
            continue
        roi = float(g["roi"].mean())
        factor = bucket(roi)
        prior[cat] = {"factor": factor, "roi": round(roi, 4), "samples": int(len(g))}
        log.append(f"  {cat}: 样本{len(g)} 单均资金利润率{roi*100:.1f}% -> 因子 {factor}")

    out = {
        "_note": "由 work/ledger_prior.py 从个人账单生成，账单更新后重跑；因子含义见 DIFF_STRATEGY.md v2",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "prior": prior,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("账单先验 ->", OUT)
    print("\n".join(log))


if __name__ == "__main__":
    main()
