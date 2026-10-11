# -*- coding: utf-8 -*-
"""得物详情页 H5 读取器。

得物对外的分享落地页（m.dewu.com/router/product/ProductDetail?spuId=xxx，小写 product）
对任意浏览器放行，无需登录、无需手机环境——从页面直接读：
商品名、当前价、主货号、规格参数。
"""
import re
import sys

from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")


def fetch_spu(spu_id, timeout_ms=20000):
    """返回 {name, price, article_no, raw_len}；读不到字段时值为 None。"""
    out = {"spu_id": str(spu_id), "name": None, "price": None, "article_no": None}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=UA, viewport={"width": 390, "height": 844})
        pg = ctx.new_page()
        try:
            pg.goto(f"https://m.dewu.com/router/product/ProductDetail?spuId={spu_id}",
                    timeout=timeout_ms, wait_until="domcontentloaded")
            # 滚动触发懒加载（规格表/销量在页面下部）
            for _ in range(4):
                try:
                    pg.evaluate("window.scrollBy(0, 900)")
                except Exception:
                    pass  # 无效 spuId 会中途跳页（evoke/下载页），此时无数据可读
                pg.wait_for_timeout(1500)
            if "roductDetail" not in pg.url and "evoke" in pg.url or "apk." in pg.url:
                out["skipped"] = pg.url[:80]  # 被弹端/下载页，价格留空
                return out
            pg.wait_for_timeout(6000)  # fast.dewu.com 落地页渲染较慢
            t = pg.evaluate("document.body.innerText")
            out["raw_len"] = len(t)
            m = re.search(r"¥\s?([0-9]{1,6}(?:\.\d{1,2})?)", t)
            if m:
                out["price"] = float(m.group(1))
            m = re.search(r"主货号[:：\s]*([A-Za-z0-9][A-Za-z0-9\-]{3,20})", t)
            if m:
                out["article_no"] = m.group(1)
            # 商品名：第一个价格之后的非埋点文本行
            lines = [x.strip() for x in t.split("\n") if x.strip()]
            for i, ln in enumerate(lines):
                if ln.startswith("¥") and i + 1 < len(lines) and len(lines[i + 1]) > 6:
                    out["name"] = lines[i + 1][:60]
                    break
            if out["name"] is None:
                junk = re.compile(r"pozionSpace|打开App|立即|版权|沪ICP")
                cands = [x for x in lines if 8 < len(x) < 40 and not junk.search(x)]
                if cands:
                    out["name"] = cands[0]
        finally:
            b.close()
    return out


if __name__ == "__main__":
    for sid in (sys.argv[1:] or ["74593642"]):
        r = fetch_spu(sid)
        print(r)
