# -*- coding: utf-8 -*-
"""
淘宝联盟 API 客户端（淘宝客 tbk）
================================
网关 https://gw.api.taobao.com/router/rest，md5 签名（实测 hmac-md5 不行，用 md5）。
密钥从环境变量 TBK_APPKEY / TBK_APPSECRET 读取。

已开通权限：物料信息查询(16189) → taobao.tbk.item.info.get
申请中权限：物料搜索(16516) → taobao.tbk.dg.material.optional（未批时返回 PermissionError，
source_allies 会优雅降级）
"""
import hashlib
import os
import time

import requests

GATEWAY = "https://gw.api.taobao.com/router/rest"


class TbkPermissionError(PermissionError):
    """权限包未开通时抛出，调用方降级跳过。"""


def _creds():
    key = os.environ.get("TBK_APPKEY") or ""
    secret = os.environ.get("TBK_APPSECRET") or ""
    if not key or not secret:
        raise RuntimeError("缺少 TBK_APPKEY / TBK_APPSECRET 环境变量")
    return key, secret


def tbk_call(method, extra=None, timeout=15):
    key, secret = _creds()
    params = {
        "app_key": key,
        "method": method,
        "format": "json",
        "v": "2.0",
        "sign_method": "md5",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    params.update(extra or {})
    concat = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    params["sign"] = hashlib.md5((secret + concat + secret).encode()).hexdigest().upper()
    # GitHub 海外 runner 到淘宝网关常超时，重试两次拉一把
    data = None
    for attempt in range(3):
        try:
            r = requests.get(GATEWAY, params=params, timeout=timeout + attempt * 10)
            data = r.json()
            break
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise RuntimeError(f"{method}: 网关连接超时（重试3次）")
    if "error_response" in data:
        err = data["error_response"]
        msg = str(err.get("msg", "")) + str(err.get("sub_msg", ""))
        code = err.get("code")
        if code in (7, 11) or "权限" in msg or "denied" in msg.lower() or "not passed" in msg.lower():
            raise TbkPermissionError(f"{method}: {err.get('sub_code', '')} {msg}")
        raise RuntimeError(f"{method}: code={code} {msg}")
    return data


def parse_coupon_info(coupon_info):
    """'满100元减20元' -> (门槛100, 面额20)；解析失败 (None, 0)。"""
    if not coupon_info:
        return None, 0.0
    import re
    m = re.search(r"满\s*([\d.]+)\s*元?.*减\s*([\d.]+)\s*元?", str(coupon_info))
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r"减\s*([\d.]+)\s*元?", str(coupon_info))
    return (None, float(m.group(1))) if m else (None, 0.0)


def item_price(it):
    """单条物料 -> (券后价, 原价, 券面额)。券后价 = 到手价门槛满足时 price-券额。"""
    price = float(it.get("zk_final_price") or 0)
    start, amount = parse_coupon_info(it.get("coupon_info"))
    amount = float(it.get("coupon_amount") or amount or 0)
    start = float(it.get("coupon_start_fee") or start or 0)
    net = price - amount if (amount and (not start or price >= start)) else price
    return round(max(net, 0.01), 2), price, amount


def material_search(keyword, page=1, page_size=20, require_coupon=True):
    """关键词搜券后商品（需权限包16516）。返回归一化物料列表。"""
    extra = {
        "q": keyword,
        "page_no": page,
        "page_size": page_size,
        "fields": "num_iid,title,pict_url,zk_final_price,coupon_info,coupon_start_fee,coupon_amount,volume,shop_title,user_type,click_url",
    }
    if require_coupon:
        extra["has_coupon"] = "true"
    data = tbk_call("taobao.tbk.dg.material.optional", extra)
    r = (data.get("tbk_dg_material_optional_response") or {}).get("result_list") or {}
    items = r.get("map_data") or []
    out = []
    for it in items:
        net, price, coupon = item_price(it)
        out.append({
            "num_iid": str(it.get("num_iid", "")),
            "title": it.get("title", "").replace("<span class=H>", "").replace("</span>", ""),
            "price": price,
            "coupon": coupon,
            "net_price": net,
            "volume": int(it.get("volume") or 0),
            "shop": it.get("shop_title", ""),
            "url": f"https://item.taobao.com/item.htm?id={it.get('num_iid')}",
            "click_url": it.get("click_url", ""),
        })
    return out


def item_info(num_iids):
    """按商品ID批量查信息（权限包16189，已开通）。"""
    data = tbk_call("taobao.tbk.item.info.get", {"num_iids": ",".join(str(x) for x in num_iids)})
    r = (data.get("tbk_item_info_get_response") or {}).get("results") or {}
    items = r.get("n_tbk_item") or []
    out = []
    for it in items:
        net, price, coupon = item_price(it)
        out.append({
            "num_iid": str(it.get("num_iid", "")),
            "title": it.get("title", ""),
            "price": price,
            "coupon": coupon,
            "net_price": net,
            "volume": int(it.get("volume") or 0),
            "shop": it.get("shop_title", ""),
            "url": f"https://item.taobao.com/item.htm?id={it.get('num_iid')}",
        })
    return out
