# -*- coding: utf-8 -*-
"""得物 App 自动化（雷电模拟器 + adb）。

已验证流程（2026-10-12）：
  首页搜索图标 → 输入关键词(货号/英文型号) → 回车 → 点首个联想词 →
  结果列表点首个商品卡 → 详情页 uiautomator dump 解析：
  现货价 / 比发售价 / 想要 / 穿过(我有) / 3日均价 / 最近成交流水 / 主货号 / 热销榜排名

依赖：雷电模拟器运行中、得物 App 已装（浏览无需登录）。单次抓取约 35-50 秒。
坐标基于当前雷电布局（1920x1080 平板模式），关键坐标运行时从 dump 里动态找，
找不到才退回常量。
"""
import os
import re
import subprocess
import time

ADB = r"F:\leidian\LDPlayer9\adb.exe"
SERIAL = "emulator-5554"
PKG = "com.shizhuang.duapp"

TEMP = r"C:\Users\Windows\AppData\Local\Temp"


def _adb(*args, timeout=30):
    cmd = [ADB, "-s", SERIAL] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout or ""


DANGER = re.compile(r"立即购买|还价|确认|提交订单|支付|马上抢|一键.*购")


def _dump(name, tries=3):
    """dump 当前界面并返回全部 (text, cx, cy)；动画中会 idle 失败，重试。"""
    for k in range(tries):
        r = _adb("shell", f"uiautomator dump /sdcard/{name}.xml", timeout=25)
        time.sleep(0.8)
        if "dumped" in r.lower() or "uidump" in r.lower():
            _adb("pull", f"//sdcard/{name}.xml", rf"{TEMP}\{name}.xml")
            try:
                with open(rf"{TEMP}\{name}.xml", encoding="utf-8", errors="ignore") as f:
                    xml = f.read()
            except OSError:
                xml = ""
            if xml:
                out = []
                for m in re.finditer(r'text="([^"]{1,90})"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
                    t = m.group(1).strip()
                    if t:
                        x1, y1, x2, y2 = map(int, m.groups()[1:])
                        out.append((t, (x1 + x2) // 2, (y1 + y2) // 2))
                return out
        time.sleep(2.5 * (k + 1))
    return []


def _tap(x, y):
    _adb("shell", f"input tap {x} {y}")


def _find(nodes, pattern):
    for t, cx, cy in nodes:
        if re.search(pattern, t):
            return t, cx, cy
    return None, None, None


def _home():
    """回 App 首页（连按返回，最多 4 次）。"""
    for _ in range(4):
        focus = _adb("shell", "dumpsys window | grep mCurrentFocus")
        if "HomeActivity" in focus:
            return True
        _adb("shell", "input keyevent 4")
        time.sleep(1.6)
    return "HomeActivity" in _adb("shell", "dumpsys window | grep mCurrentFocus")


def parse_detail(nodes):
    """从详情页文本流解析关键字段。"""
    texts = [t for t, _, _ in nodes]
    out = {"title": None, "price": None, "vs_msrp": None, "msrp": None,
           "article_no": None, "want": None, "owned": None, "avg3d": None,
           "rank": None, "recent": []}
    j = " | ".join(texts)

    m = re.search(r"¥\s?([\d\s]{1,12})", j.replace("¥ ", "¥"))
    if not out["price"]:
        # 详情页主价格形如 "¥ 2 3 0"（逐字分开），取 想要/主货号 之前第一个数字块
        for t in texts:
            s = t.replace(" ", "")
            if re.fullmatch(r"¥\d{2,5}", s):
                out["price"] = float(s[1:])
                break
    m = re.search(r"比发售价(低|高)¥(\d+)", j)
    if m:
        out["vs_msrp"] = ("-" if m.group(1) == "低" else "+") + m.group(2)
    m = re.search(r"¥(\d{2,5})\s*\|?\s*发售价格", j) or re.search(r"发售价格\s*\|?\s*¥?(\d{2,5})", j)
    for i, t in enumerate(texts):
        if t == "主货号" and i > 0:
            out["article_no"] = texts[i - 1]
            if i + 1 < len(texts) and texts[i + 1].startswith("¥"):
                out["msrp"] = float(texts[i + 1][1:].replace(" ", ""))
            break
    for label, key in (("想要", "want"), ("穿过", "owned"), ("我有", "owned")):
        for i, t in enumerate(texts):
            if t == label and i > 0:
                out[key] = out[key] or texts[i - 1]
                break
    m = re.search(r"3日均价¥(\d+)", j)
    if m:
        out["avg3d"] = float(m.group(1))
    m = re.search(r"([\u4e00-\u9fa5]+热销榜第\d+名)", j)
    if m:
        out["rank"] = m.group(1)
    # 最近成交流水：label 后成组 (who, size, ¥price, timeago) 直到 穿搭精选
    try:
        i = texts.index("最近购买 (2.1万+)") if "最近购买 (2.1万+)" in texts else \
            next(i for i, t in enumerate(texts) if t.startswith("最近购买"))
        for k in range(i + 1, min(i + 17, len(texts) - 3)):
            if texts[k].startswith("穿搭精选"):
                break
            if texts[k + 2].startswith("¥") and (k + 3 < len(texts)) and re.search(r"(分钟|小时|天)前", texts[k + 3]):
                out["recent"].append({"who": texts[k], "size": texts[k + 1],
                                      "price": float(texts[k + 2][1:].replace(" ", "")),
                                      "ago": texts[k + 3]})
    except (StopIteration, ValueError):
        pass
    # 标题：详情页第一个含款名特征的长文本（含空格的字母+中文混合且长度>15）
    junk = re.compile(r"先鉴别|热销榜|发售|主货号|最近购买|穿搭精选|客服|还价|立即|次日|直播|领券")
    for t in texts:
        if len(t) > 15 and not junk.search(t) and not t.startswith("¥") and "同款" not in t:
            out["title"] = t
            break
    return out


def _tokens(title):
    t = re.sub(r"【[^】]*】|\[[^\]]*\]|（[^）]*）|\([^\)]*\)", " ", str(title or ""))
    return {w for w in re.split(r"[\s/]+", t.lower()) if len(w) >= 2}


def _sim(a, b):
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def fetch_by_keyword(keyword, settle=9.0, expect=None):
    """按货号/英文型号在得物 App 内搜索并解析首个商品详情。"""
    # 冷启动：状态污染是错点根源，每次强制停止再启动（多花 ~8s 但确定性）
    _adb("shell", f"am force-stop {PKG}")
    time.sleep(1.5)
    _adb("shell", f"monkey -p {PKG} -c android.intent.category.LAUNCHER 1")
    time.sleep(9)
    # 1) 首页搜索入口：冷启动可能恢复到帖子/详情页，找到搜索或按返回，重试 4 次
    cx = cy = None
    for attempt in range(4):
        nodes = _dump("dw_home")
        _, cx, cy = _find(nodes, r"^搜索$|搜索你想要|搜同款|搜索：")
        if cx:
            break
        _adb("shell", "input keyevent 4")
        time.sleep(2.0)
    if cx is None:
        cx, cy = 1766, 80  # 冷启动首页搜索入口的实测坐标
    _tap(cx, cy)
    time.sleep(3.5)
    # 2) 定位搜索页顶部输入框（y<120 的第一个文本节点），点进去清残留再输入
    nodes2 = _dump("dw_sp")
    box = next(((t, cx, cy) for t, cx, cy in nodes2 if cy < 120 and t != "搜索"), None)
    if box:
        _tap(box[1], box[2])
        time.sleep(1.0)
    else:
        _tap(960, 80)  # 搜索页顶部输入区兜底
        time.sleep(1.0)
    _adb("shell", "input keyevent 123")            # MOVE_END
    for _ in range(30):
        _adb("shell", "input keyevent 67")         # DEL 逐字清空残留查询
    _adb("shell", f'input text "{keyword}"')
    time.sleep(2.0)
    # 3) 点右上角「搜索」按钮提交（联想面板会在 dump 间隙收起，按钮是常驻稳定的）
    for attempt in range(2):
        nodes = _dump("dw_sug")
        _, sx, sy = _find(nodes, r"^搜索$")
        if sx is None:
            sx, sy = 1854, 80
        assert True
        _tap(sx, sy)
        time.sleep(8.0)
        nodes = _dump("dw_res")
        if any(t in ("商品", "筛选") for t, _, _ in nodes):
            break
        time.sleep(4)
    # 4) 结果列表（步骤3的重试循环里已 dump；这里兜底再取一次）
    if 'nodes' not in dir() or not nodes:
        nodes = _dump("dw_res")
    has_tabs = any(t in ("商品", "筛选") for t, _, _ in nodes)
    if not has_tabs:  # 慢加载宽限一轮
        time.sleep(5)
        nodes = _dump("dw_res")
        has_tabs = any(t in ("商品", "筛选") for t, _, _ in nodes)
    if has_tabs:
        # 切「商品」页签：默认混排会插社区帖（同款名帖子会污染候选卡）
        _, gx, gy = _find(nodes, r"^商品$")
        if gx:
            _tap(gx, gy)
            time.sleep(5)
            nodes = _dump("dw_res")
    if not has_tabs and not any(t == "商品" for t, _, _ in nodes):
        return {"error": "未进入结果页", "screen": [t for t, _, _ in nodes][:10]}
    cand = sorted([n for n in nodes if n[2] > 380 and len(n[0]) > 8
                   and not re.search(r"¥|筛选|同款|人付款|人在围观|直播|买手|穿搭|榜单|定制|客制", n[0])],
                  key=lambda n: (n[2], n[1]))  # 先按行再按列：取第一行的最左卡
    if expect and cand:
        # 配色防错（双层）：①期望标题里的颜色词必须在候选标题中出现；②按相似度排序。
        # （搜索结果常混入同款异配色/定制款，点错配色=价格全错）
        colors = set(re.findall(r"[黑白灰蓝红粉紫绿黄银米棕褐]色?", expect))
        strict = [n for n in cand if not colors or any(c in n[0] for c in colors)]
        seen = list(cand)
        for _ in range(3):
            if strict or not colors:
                break
            # 可见卡全是异配色/周边：往下翻一屏继续找官方款
            _adb("shell", "input swipe 960 780 960 320")
            time.sleep(4)
            nodes = _dump("dw_res3")
            new_cards = [n for n in nodes if n[2] > 300 and len(n[0]) > 8
                         and not re.search(r"¥|筛选|同款|人付款|人在围观|直播|买手|穿搭|榜单|定制|客制", n[0])
                         and not any(abs(n[1]-o[1]) < 60 and abs(n[2]-o[2]) < 60 for o in seen)]
            seen += new_cards
            strict = [n for n in new_cards if not colors or any(c in n[0] for c in colors)]
        if colors and not strict:
            return {"keyword": keyword,
                    "error": f"配色不匹配：期望含{colors}，翻页后仍未找到官方款"}
        use = sorted(strict, key=lambda n: -_sim(n[0], expect))
        _simcache = use[0]
        if _sim(_simcache[0], expect) < 0.3:
            # 可见卡全不像：往下翻一屏再找
            _adb("shell", "input swipe 960 780 960 380")
            time.sleep(4)
            nodes = _dump("dw_res2")
            more = [n for n in nodes if n[2] > 300 and len(n[0]) > 8
                    and not re.search(r"¥|筛选|同款|人付款|人在围观|直播|买手|穿搭|榜单|定制|客制", n[0])]
            more = [n for n in more if not any(abs(n[2]-o[1]) < 60 and abs(n[3]-o[2]) < 60 for o in cand)]
            if more:
                best_more = sorted(more, key=lambda n: -_sim(n[0], expect))[0]
                if _sim(best_more[0], expect) > _sim(use[0], expect):
                    use = [best_more] + use
        cand = use
    if not cand:
        return {"error": "结果页无商品卡", "screen": [t for t, _, _ in nodes][:12]}
    # 5) 逐候选进详情，主货号与搜索词一致才算命中（颜色/型号仿冒通行证全失效）
    kw_norm = re.sub(r"[^A-Z0-9]", "", keyword.upper())
    attempts, warns = [], []
    for node in cand[:3]:
        _tap(node[1], node[2])
        time.sleep(settle)
        nodes = _dump("dw_det")
        detail = parse_detail(nodes)
        detail["keyword"] = keyword
        found = re.sub(r"[^A-Z0-9]", "", (detail.get("article_no") or "").upper())
        if not found:
            warns.append(f"{node[0][:16]}(详情无货号)")
            _adb("shell", "input keyevent 4")
            time.sleep(2.5)
            continue
        if found == kw_norm:
            detail["verified"] = True
            _home()
            return detail
        attempts.append(f"{found}:{detail.get('price')}({node[0][:14]})")
        _adb("shell", "input keyevent 4")
        time.sleep(2.5)
    detail["verified"] = False
    detail["tried"] = attempts or warns
    _home()
    return detail


def fetch_batch(pairs, sleep_s=20.0):
    """pairs: [(keyword, expect_title_or_None), ...]"""
    out = []
    for kw, expect in pairs:
        try:
            r = fetch_by_keyword(kw, expect=expect)
        except Exception as e:
            r = {"keyword": kw, "error": str(e)[:80]}
        out.append(r)
        print(r)
        time.sleep(sleep_s)
    return out


if __name__ == "__main__":
    import sys
    kws = [(k, None) for k in (sys.argv[1:] or ["237153-BKGY"])]
    fetch_batch(kws, sleep_s=5)
