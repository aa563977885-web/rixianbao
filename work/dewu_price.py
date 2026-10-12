# -*- coding: utf-8 -*-
"""得物分享落地页读取器（仅元数据版）。

页面（router/product/ProductDetail?spuId=xxx，任意浏览器放行）上唯一的 ¥ 价格是
「发售价格」= 官方发售价，**不是得物现货价**（现货价接口 detailV5 未登录返回 403，
页面的"立即购买"只唤起 App）。因此本工具只产出：
  name（商品名）/ article_no（主货号）/ msrp（官方发售价，供参考）
不产出 du_price——现货价以门道爬虫的「最低价」为准（每 4h 更新）。
"""
import re
import sys

from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")


def fetch_spu(spu_id, timeout_ms=20000):
    """返回 {spu_id, name, article_no, msrp}；被弹端/无效时带 skipped。"""
    out = {"spu_id": str(spu_id), "name": None, "article_no": None, "msrp": None}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=UA, viewport={"width": 390, "height": 844})
        pg = ctx.new_page()
        try:
            pg.goto(f"https://m.dewu.com/router/product/ProductDetail?spuId={spu_id}",
                    timeout=timeout_ms, wait_until="domcontentloaded")
            for _ in range(3):
                try:
                    pg.evaluate("window.scrollBy(0, 900)")
                except Exception:
                    pass
                pg.wait_for_timeout(1500)
            if "evoke" in pg.url or "apk." in pg.url or "apple" in pg.url:
                out["skipped"] = pg.url[:80]
                return out
            pg.wait_for_timeout(5000)
            t = pg.evaluate("document.body.innerText")
            out["raw_len"] = len(t)
            m = re.search(r"主货号[:：\s]*([A-Za-z0-9][A-Za-z0-9\-]{3,20})", t)
            if m:
                out["article_no"] = m.group(1)
            m = re.search(r"发售价格[:：\s]*¥?\s?([0-9]{1,6}(?:\.\d{1,2})?)", t)
            if m:
                out["msrp"] = float(m.group(1))
            lines = [x.strip() for x in t.split("\n") if x.strip()]
            junk = re.compile(r"pozionSpace|打开App|立即|版权|沪ICP|常见问题|想要|购买|鉴别|Q：")
            cands = [x for x in lines if 8 < len(x) < 40 and not junk.search(x)]
            if cands:
                out["name"] = cands[0]
        finally:
            b.close()
    return out


if __name__ == "__main__":
    for sid in (sys.argv[1:] or ["1168907"]):
        print(fetch_spu(sid))
