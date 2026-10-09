# -*- coding: utf-8 -*-
"""
联盟券价源：淘宝联盟 + 京东联盟 -> data/pool.json（source=tbk/jd，du_price=None）
================================================================================
这是"自己的线报"的源头层：联盟 API 的券后商品天然自带价差入口，
产出候选进入现有 打分/建站/晨报/待核价清单 流水线。得物价(du_price)留空，
页面上归入「🆕 联盟新券·待核价」，由你 App 核价后补齐。

用法:
  python work/source_allies.py            # 按 config/allies.json 拉取
  python work/source_allies.py --keyword 阿迪达斯   # 临时加一个关键词
密钥: 环境变量 TBK_APPKEY/TBK_APPSECRET/JD_UNION_APPKEY/JD_UNION_APPSECRET（Actions Secrets）。
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_client  # noqa: E402
import tbk_client  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(ROOT, "config", "allies.json")
POOL = os.path.join(ROOT, "data", "pool.json")
EXPOSURE = os.path.join(ROOT, "data", "exposure.json")
PRICE_HISTORY = os.path.join(ROOT, "data", "price_history.json")


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def classify(title):
    t = str(title or "")
    for kws, cat in [
        (["鞋", "板鞋", "跑鞋", "篮球鞋", "帆布鞋", "AF1", "Dunk"], "球鞋"),
        (["香水", "粉底", "气垫", "遮瑕", "口红", "精华", "面霜", "面膜", "护肤"], "美妆"),
        (["羽绒", "外套", "卫衣", "T恤", "裤", "衬衫", "毛衣", "大衣"], "服饰"),
        (["背包", "双肩包", "挎包", "露营", "帐篷"], "户外"),
        (["耳机", "手表", "手机", "平板", "充电宝", "键盘"], "数码"),
    ]:
        if any(k in t for k in kws):
            return cat
    return "其他"


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def collect(conf, extra_keyword=None):
    """拉取双联盟候选，返回归一化条目列表。单源失败不影响另一源。"""
    ts = now_iso()
    items = []
    notes = []

    # 淘宝：关键词券后物料（需权限包16516，未批时降级跳过）
    try:
        import tbk_client as tbk
        kws = list(conf.get("tbk_keywords", []))
        if extra_keyword:
            kws.append(extra_keyword)
        for kw in kws:
            try:
                found = tbk.material_search(kw, page_size=20)
            except tbk.TbkPermissionError as e:
                notes.append(f"[tbk] 物料搜索权限未开通，关键词扫描跳过（{str(e)[:60]}）")
                break
            except RuntimeError as e:
                notes.append(f"[tbk] {kw} 失败: {str(e)[:60]}")
                continue
            for it in found:
                items.append({
                    "carry_id": f"tbk-{it['num_iid']}",
                    "title": it["title"],
                    "category": classify(it["title"]),
                    "cost": it["net_price"],
                    "gross": it["price"],
                    "coupon": it["coupon"],
                    "source": "tbk",
                    "sales_7d": it["volume"],
                    "url": it["url"],
                    "published_at": ts,
                })
            notes.append(f"[tbk] {kw}: {len(found)} 条")
    except RuntimeError as e:
        notes.append(f"[tbk] 跳过: {str(e)[:60]}")

    # 京东：热销榜（已开通）+ 关键词（V1解锁前自动跳过）
    try:
        import jd_client as jd
        for rid in conf.get("jd_rank_ids", []):
            try:
                found = jd.goods_rank(rid, page_size=20)
            except jd.JdPermissionError as e:
                notes.append(f"[jd] 榜单{rid} 跳过: {str(e)[:60]}")
                continue
            except RuntimeError as e:
                notes.append(f"[jd] 榜单{rid} 失败: {str(e)[:60]}")
                continue
            for it in found:
                items.append({
                    "carry_id": f"jd-{it['sku_id']}",
                    "title": it["title"],
                    "category": classify(it["title"]),
                    "cost": it["lowest_price"] or it["price"],
                    "gross": it["price"],
                    "coupon": 0,
                    "source": "jd",
                    "sales_7d": None,
                    "url": it["url"],
                    "published_at": ts,
                })
            notes.append(f"[jd] 榜单{rid}: {len(found)} 条")
        if conf.get("jd_keywords"):
            for kw in conf["jd_keywords"]:
                try:
                    found = jd.goods_query(kw, page_size=10)
                except jd.JdPermissionError:
                    notes.append("[jd] 关键词搜索需V1等级，跳过")
                    break
                for it in found:
                    items.append({
                        "carry_id": f"jd-{it['sku_id']}",
                        "title": it["title"],
                        "category": classify(it["title"]),
                        "cost": it["lowest_price"] or it["price"],
                        "gross": it["price"],
                        "coupon": 0,
                        "source": "jd",
                        "sales_7d": None,
                        "url": it["url"],
                        "published_at": ts,
                    })
                notes.append(f"[jd] {kw}: {len(found)} 条")
    except RuntimeError as e:
        notes.append(f"[jd] 跳过: {str(e)[:60]}")

    return items, notes


def main():
    ap = argparse.ArgumentParser(description="联盟券价源")
    ap.add_argument("--keyword", default=None, help="临时追加淘宝关键词")
    args = ap.parse_args()

    conf = load_json(CONF, {})
    items, notes = collect(conf, args.keyword)
    for n in notes:
        print(n)

    pool = load_json(POOL, [])
    if isinstance(pool, list):
        pool_map = {str(d.get("carry_id")): d for d in pool if d.get("carry_id")}
    else:
        pool_map = {str(k): v for k, v in pool.items()}
    exposure = load_json(EXPOSURE, {})
    history = load_json(PRICE_HISTORY, {})
    ts = now_iso()
    new_count = 0
    for it in items:
        cid = it["carry_id"]
        prev = pool_map.get(cid)
        if prev:
            prev.update({k: v for k, v in it.items() if k not in ("first_seen",)})
            prev["last_seen"] = ts
        else:
            it["first_seen"] = ts
            it["last_seen"] = ts
            it["seen_count"] = 0
            it["net_profit"] = None  # 得物价未知，App核价后人工补
            pool_map[cid] = it
            new_count += 1
        e = exposure.setdefault(cid, {"first_seen": ts, "seen_count": 0})
        e["last_seen"] = ts
        # 记录货源价轨迹（ alliances 侧 cost = 券后价）
        seq = history.setdefault(cid, [])
        if not seq or seq[-1][1] != it["cost"]:
            seq.append([ts, it["cost"], None])
            history[cid] = seq[-60:]

    save_json(POOL, list(pool_map.values()))
    save_json(EXPOSURE, exposure)
    save_json(PRICE_HISTORY, history)
    print(f"汇总：联盟候选 {len(items)} 条 | 新增 {new_count} | 池子共 {len(pool_map)} 条")


if __name__ == "__main__":
    main()
