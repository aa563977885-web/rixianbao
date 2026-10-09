# -*- coding: utf-8 -*-
"""
每日晨报推送：data/scored.json -> 微信(Server酱) / iOS(Bark)
=============================================================
一条消息讲完今天：新冷门优选 + 盯款雷达降价 + 全局统计。
每天两次运行都推（短心跳+有货时详细），Server酱免费额度(5条/天)内。

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
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORED = os.path.join(ROOT, "data", "scored.json")
NOTIFIED = os.path.join(ROOT, "data", "notified.json")
SITE = "https://aa563977885-web.github.io/rixianbao/"
BEIJING = timezone(timedelta(hours=8))


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


def build_digest(scored, notified_ids):
    """返回 (title, body, new_cold_ids)。一条消息：新机会 + 降价雷达 + 统计。"""
    cold = [x for x in scored if x.get("verdict") == "冷门优选"]
    new_cold = [x for x in cold if str(x.get("carry_id")) not in notified_ids][:3]
    drops = [x for x in scored if x.get("verdict") == "可蹲·降价中"][:3]
    watch = [x for x in scored if x.get("verdict") in ("可蹲", "可蹲·降价中")]
    n_ok = sum(1 for x in scored if (x.get("net_profit") or 0) >= 50)

    parts = []
    if new_cold:
        lines = [f"⭐ {x.get('title')}｜净利+{x.get('net_profit')}元｜曝光{x.get('seen_count')}次"
                 for x in new_cold]
        parts.append("【新冷门优选】\n" + "\n".join(lines))
    if drops:
        lines = []
        for x in drops:
            tr = x.get("price_trend") or {}
            lines.append(f"📉 {x.get('title')}｜¥{tr.get('first')}→¥{tr.get('last')}"
                         f"({tr.get('pct'):+}%)｜现净利+{x.get('net_profit')}元")
        parts.append("【盯款雷达·降价中】\n" + "\n".join(lines))
    parts.append(f"——\n今日候选{len(scored)}条｜净利≥50共{n_ok}条｜可蹲{len(watch)}条\n{SITE}")

    max_net = max((x.get("net_profit") or 0 for x in new_cold), default=0)
    if new_cold:
        title = f"线报晨报:新机会{len(new_cold)} 最高+{max_net:.0f}元"
    elif drops:
        title = f"线报晨报:降价{len(drops)} 可蹲{len(watch)}"
    else:
        title = f"线报晨报:无爆点 可蹲{len(watch)}"
    return title, "\n\n".join(parts), [str(x.get("carry_id")) for x in new_cold]


def main():
    dry_run = "--dry-run" in sys.argv
    scored = load_json(SCORED, [])
    if not scored:
        print("缺少 data/scored.json，先跑 work/scoring.py")
        return
    notified_ids = set(load_json(NOTIFIED, []))
    title, body, new_ids = build_digest(scored, notified_ids)
    now_bj = datetime.now(BEIJING)
    # 节流（Server酱免费5条/天）：无新内容时只在早8点这轮发心跳
    has_content = bool(new_ids) or "降价" in title
    if not has_content and now_bj.hour != 8:
        print("[skip] 无新机会且非早报时段，不推送")
        return
    title = f"{now_bj.strftime('%m-%d %H:%M')} {title}"

    print("标题:", title)
    print("正文:\n" + body)

    if dry_run:
        print("[dry-run] 不发送、不更新已推送记录")
        return

    key = os.environ.get("SERVERCHAN_SENDKEY")
    bark = os.environ.get("BARK_KEY")
    sent = False
    if key:
        sent = send_serverchan(key, title, body) or sent
    if bark:
        sent = send_bark(bark, title, body) or sent
    if not key and not bark:
        print("[warn] 未设置 SERVERCHAN_SENDKEY / BARK_KEY，跳过推送（本地验证请用 --dry-run）")
        return

    if sent and new_ids:
        notified_ids.update(new_ids)
        save_json(NOTIFIED, sorted(notified_ids))
        print(f"已推送，新冷门优选记录 {len(new_ids)} 条已登记")


if __name__ == "__main__":
    main()
