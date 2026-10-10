#!/usr/bin/env python3
"""本机定时任务：拉联盟源（淘宝网关只有本机网络能通）→ 打分渲染 → 有实质变化才提交推送。

推送 data/ 后由 .github/workflows/deploy_on_push.yml 自动部署站点，
本脚本不直接部署。重复数据（榜单没变）不推送，避免提交噪音。
"""
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
SIG_FILE = os.path.join(ROOT, "outputs", ".local_pool_sig")  # outputs/ 已 gitignore


def run(cmd, **kw):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def pool_signature():
    """池子的实质内容签名：只看 ID/价格/来源，忽略 last_seen 等时间戳。"""
    try:
        with open(os.path.join(ROOT, "data", "pool.json"), encoding="utf-8") as f:
            pool = json.load(f)
    except (OSError, ValueError):
        return "missing"
    sig = sorted((str(i.get("carry_id")), str(i.get("cost")), str(i.get("du_price")),
                  str(i.get("source"))) for i in pool)
    return hashlib.md5(json.dumps(sig, ensure_ascii=False).encode()).hexdigest()


def main():
    # 1) 拉联盟源（jd+tbk；密钥从 config/local_secrets.json 读，见各 client 的 _creds 兜底）
    code, out = run([PY, os.path.join("work", "source_allies.py")])
    print(out.strip()[-500:])
    if code != 0:
        print("[local] source_allies 失败，退出")
        return

    # 2) 实质无变化 → 不推送（站点下轮 CI 照常跑）
    sig = pool_signature()
    prev = ""
    try:
        with open(SIG_FILE, encoding="utf-8") as f:
            prev = f.read().strip()
    except OSError:
        pass
    if sig == prev or sig == "missing":
        print("[local] 池子无实质变化，不推送")
        return
    os.makedirs(os.path.dirname(SIG_FILE), exist_ok=True)
    with open(SIG_FILE, "w", encoding="utf-8") as f:
        f.write(sig)

    # 3) 打分 + 清单 + 渲染
    for step in ("scoring.py", "export_tracker.py", "make_html.py"):
        code, out = run([PY, os.path.join("work", step)])
        print(f"[local] {step}: rc={code}")
        if code != 0:
            print(out[-300:])
            return

    # 4) 提交推送（rebase 撞 CI 自动提交时，数据文件取本地新做的）
    run(["git", "add", "data/", "config/allies.json"])
    _rc, status = run(["git", "status", "--porcelain", "data/"])
    if not status.strip():
        print("[local] 无可提交内容")
        return
    run(["git", "commit", "-m", "chore: 本地联盟源拉取"])
    c, out = run(["git", "pull", "--rebase"])
    if "Could not apply" in out or "CONFLICT" in out:
        for f in ("data/scored.json", "data/pool.json"):
            run(["git", "checkout", "--theirs", f])
        run(["git", "add", "data/"])
        run(["git", "rebase", "--continue"], env={**os.environ, "GIT_EDITOR": "true"})
    c1, out1 = run(["git", "push"])
    print("[local] push:", "OK" if c1 == 0 else out1[-200:])


if __name__ == "__main__":
    main()
