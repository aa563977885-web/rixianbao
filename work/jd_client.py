# -*- coding: utf-8 -*-
"""
京东联盟 API 客户端
==================
网关 https://api.jd.com/routerjson，md5 签名，业务参数打包为 360buy_param_json。
密钥从环境变量 JD_UNION_APPKEY / JD_UNION_APPSECRET 读取。

已开通：goods.rank.query（热销榜）、order.row.query、selling.goods.query（按SKU查商品）。
V1 等级解锁：goods.query（关键词搜索）、coupon.query（券查询）——未到等级时抛 JdPermissionError。
"""
import hashlib
import json
import os
import time

import requests

GATEWAY = "https://api.jd.com/routerjson"


class JdPermissionError(PermissionError):
    """权限/等级不足时抛出，调用方降级跳过。"""


def _creds():
    key = os.environ.get("JD_UNION_APPKEY") or ""
    secret = os.environ.get("JD_UNION_APPSECRET") or ""
    if not key or not secret:
        # 本机定时任务兜底：config/local_secrets.json（已 gitignore，不进仓库）
        try:
            with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "config", "local_secrets.json"), encoding="utf-8") as f:
                s = json.load(f)
            key = key or s.get("JD_UNION_APPKEY", "")
            secret = secret or s.get("JD_UNION_APPSECRET", "")
        except (OSError, ValueError):
            pass
    if not key or not secret:
        raise RuntimeError("缺少 JD_UNION_APPKEY / JD_UNION_APPSECRET 环境变量")
    return key, secret


def _bj_now():
    """京东路由按北京时间校验 timestamp；GitHub runner 是 UTC，必须显式取东八区。"""
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def jd_call(method, req=None, timeout=15):
    key, secret = _creds()
    params = {
        "method": method,
        "app_key": key,
        "access_token": "",
        "timestamp": _bj_now(),
        "format": "json",
        "v": "1.0",
        "sign_method": "md5",
        "360buy_param_json": json.dumps(req or {}, ensure_ascii=False, separators=(",", ":")),
    }
    concat = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    params["sign"] = hashlib.md5((secret + concat + secret).encode()).hexdigest().upper()
    r = requests.post(GATEWAY, data=params, timeout=timeout)
    data = r.json()
    if "error_response" in data:
        err = data["error_response"]
        msg = str(err.get("msg", "")) + str(err.get("zh_desc", "")) + str(err.get("desc", ""))
        code = err.get("code")
        if code in (7, 8, 12, 15, 16) or "权限" in msg or "无权" in msg or "不存在" in msg:
            raise JdPermissionError(f"{method}: {msg[:120]}")
        raise RuntimeError(f"{method}: code={code} {msg[:120]}")
    resp = data.get(method.replace(".", "_") + "_responce") or data.get(method + "_response") or {}
    if not resp:
        # 京东返回键名形如 jd_union_open_goods_rank_query_responce
        for k, v in data.items():
            if k.endswith("_responce") or k.endswith("_response"):
                resp = v
                break
    return resp


# 榜单ID枚举：200000 全部 / 200001 食品酒水 / 200002 家庭清洁 / 200003 个护美妆 /
# 200004 医药保健 / 200005 生鲜 / 200006 数码家电 / 200007 家居日用 / 200008 时尚生活
def goods_rank(rank_id, page=1, page_size=20):
    """热销榜商品。注意：入参包装键是字面量 RankGoodsReq（首字母大写，
    与官方文档页/PHP SDK 示例一致；小写 rankGoodsReq 会报 400 参数错误）。"""
    data = jd_call("jd.union.open.goods.rank.query", {
        "RankGoodsReq": {"rankId": int(rank_id), "sortType": 3,
                         "pageIndex": page, "pageSize": page_size},
    })
    qr = (data.get("queryResult") or {})
    if isinstance(qr, str):
        try:
            qr = json.loads(qr)
        except ValueError:
            return []
    if not isinstance(qr, dict):
        return []
    out = []
    for it in qr.get("data") or []:
        g = it.get("rankGoodsResp") or it
        pid = g.get("purchasePriceInfo") or {}
        wl = float(g.get("wlprice") or 0)
        purchase = float(pid.get("purchasePrice") or wl)
        coupon = max([float(c.get("discount") or 0) for c in (pid.get("couponList") or [])] or [0])
        sku = str(g.get("skuId") or g.get("itemId") or "")
        out.append({
            "sku_id": sku,
            "title": g.get("skuName", ""),
            "price": wl,
            "lowest_price": round(max(purchase - coupon, 0), 2),
            "shop": "",
            "commission": round(wl * float(g.get("commissionShare") or 0) / 100, 2),
            "url": f"https://item.jd.com/{sku}.html" if sku else "",
        })
    return out


def goods_query(keyword, page=1, page_size=10):
    """关键词商品查询（需V1等级解锁）。"""
    data = jd_call("jd.union.open.goods.query", {"req": {"keyword": keyword, "pageIndex": page, "pageSize": page_size}})
    qr = (data.get("queryResult") or {})
    out = []
    for it in qr.get("data") or []:
        base = it.get("baseInfo") or {}
        price_info = it.get("priceInfo") or {}
        price = float((price_info.get("price") or 0))
        out.append({
            "sku_id": str(base.get("skuId") or ""),
            "title": base.get("skuName", ""),
            "price": price,
            "lowest_price": float((price_info.get("lowestPrice") or price) or 0),
            "shop": (it.get("shopInfo") or {}).get("shopName", ""),
            "url": f"https://item.jd.com/{base.get('skuId')}.html",
        })
    return out
