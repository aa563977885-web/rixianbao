# -*- coding: utf-8 -*-
"""
冷门优选推送：对比上轮 scored.json，新出现的「⭐冷门优选」推微信(Server酱) / iOS(Bark)
========================================================================================
用法:
  python work/notify.py            # 正式推送（需 SERVERCHAN_SENDKEY 或 BARK_KEY 环境变量）
  python work/notify.py --dry-run  # 干跑：只打印标题/正文，不发送、不记录

密钥从环境变量读取，禁止写死：
  SERVERCHAN_SENDKEY   Server酱 SendKey（https://sct.ftqq.com 获取）
  BARK_KEY             Bark 设备 key（可选，iOS 备用）
网络失败只打日志，不使 workflow 变红。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORED = os.path.join(ROOT, "data", "scored.json")
NOTIFIED = os.path.join(ROOT, "data", "notified.json")
SITE = "https://aa563977885-web.github.io/rixianbao/"


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def send_serverchan(key, title, desp):
    try:
        import requests
        r = requests.post(f"https://sctapi.ftqq.com/{key}.send",
                          data={"title": title, "desp": desp}, timeout=15)
        rj = r.json()
        print(f"[serverchan] code={rj.get('code')} {rj.get('message', '')}".strip())
        return rj.get("code") == 0
    except Exception as e:
        print("[serverchan] 发送失败（不影响流程）:", str(e)[:120])
        return False


def send_bark(key, title, body):
    try:
        import urllib.parse
        import requests
        url = (f"https://api.day.app/{key}/{urllib.parse.quote(title)}/"
               f"{urllib.parse.quote(body)}?url={urllib.parse.quote(SITE)}")
        r = requests.get(url, timeout=15)
        print(f"[bark] status={r.status_code} {r.text[:80]}")
        return r.status_code == 200
    except Exception as e:
        print("[bark] 发送失败（不影响流程）:", str(e)[:120])
        return False


def main():
    dry_run = "--dry-run" in sys.argv
    scored = load_json(SCORED, [])
    cold = [x for x in scored if x.get("verdict") == "冷门优选"]
    notified = set(load_json(NOTIFIED, []))
    new = [x for x in cold if str(x.get("carry_id")) not in notified]
    if not new:
        print("无新冷门优选，跳过推送")
        return

    max_net = max((x.get("net_profit") or 0 for x in new), default=0)
    title = f"冷门优选+{len(new)}条 | 最高净利{max_net:.0f}元"
    lines = [f"{x.get('title')} | 净利{x.get('net_profit')}元 | 曝光{x.get('seen_count')}次" for x in new]
    body = "\n".join(lines) + f"\n\n查看完整线报: {SITE}"

    print("标题:", title)
    print("正文:\n" + body)

    if dry_run:
        print("[dry-run] 不发送、不更新已推送记录")
        return

    key = os.environ.get("SERVERCHAN_SENDKEY")
    bark = os.environ.get("BARK_KEY")
    if key:
        send_serverchan(key, title, body)
    if bark:
        send_bark(bark, title, body)
    if not key and not bark:
        print("[warn] 未设置 SERVERCHAN_SENDKEY / BARK_KEY，跳过推送（本地验证请用 --dry-run）")

    notified.update(str(x.get("carry_id")) for x in new)
    save_json(NOTIFIED, sorted(notified))
    print(f"已推送 {len(new)} 条，已推送记录已更新")


if __name__ == "__main__":
    main()
