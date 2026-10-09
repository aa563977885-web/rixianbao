# -*- coding: utf-8 -*-
"""
流水线失败告警：daily.yml 任一步骤失败时推一条微信/iOS，避免静默死掉。
在 workflow 里以 `if: failure()` 调用；密钥同 notify.py。
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from notify import send_bark, send_serverchan  # noqa: E402

BEIJING = timezone(timedelta(hours=8))


def main():
    step = "未知步骤"
    for a in sys.argv[1:]:
        if a.startswith("--step="):
            step = a.split("=", 1)[1]
    stamp = datetime.now(BEIJING).strftime("%m-%d %H:%M")
    title = f"⚠️ 线报流水线失败 {stamp}"
    body = f"步骤「{step}」执行失败，站点本轮未更新。\n可能原因：门道改版/反爬、联盟接口变动、依赖报错。\n请到 GitHub Actions 查看日志：https://github.com/aa563977885-web/rixianbao/actions"
    print(title + "\n" + body)
    key = os.environ.get("SERVERCHAN_SENDKEY")
    bark = os.environ.get("BARK_KEY")
    sent = False
    if key:
        sent = send_serverchan(key, title, body) or sent
    if bark:
        sent = send_bark(bark, title, body) or sent
    if not key and not bark:
        print("[warn] 未配置推送密钥，失败告警无法送达（请配 SERVERCHAN_SENDKEY）")


if __name__ == "__main__":
    main()
