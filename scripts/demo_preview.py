#!/usr/bin/env python3
"""一键演示预演：自动登录并依次执行演示脚本的全部案例，生成可投屏的 Markdown 报告。

用法：
    uv run python scripts/demo_preview.py [--out demo/preview.md]

演示日流程（最省事）：
    1. 先跑本脚本预演 → 若配额/服务异常，报告里会标注，当场就能发现
    2. 现场：打开前端 http://localhost:5173 （tester / test123456）照念 demo-script.md 的提示词；
       或直接把生成的 preview.md 投屏，逐条念「提示词 → 晓问回答」
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

BASE = "http://127.0.0.1:8000"

# 与 docs/demo-script.md 速查表一一对应：每个案例独立 conversation（模拟「新对话」）
CASES = [
    ("知识问答·政策", "出差住宿标准是什么？一线城市能住多少钱？"),
    ("行程规划·杭州", "帮我规划行程：下周三从北京去杭州出差拜访客户，待2晚，高铁往返"),
    ("偏好记忆·记录", "我不吃辣，住宿喜欢安静，常住成都"),
    ("偏好记忆·验证", "帮我规划行程：下周五从成都去西安开会，待1晚，飞机往返"),
    ("历史记忆·档案", "我最近有哪些行程？杭州那次出差安排是什么？"),
    ("信息查询·天气", "杭州明天天气怎么样？"),
    ("信息查询·汇率", "100美元等于多少人民币？"),
]


def _post(path: str, payload: dict, token: str | None = None, timeout: int = 150) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, json.dumps(payload).encode(), headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _login() -> str:
    d = _post("/api/auth/login", {"username": "tester", "password": "test123456"}, timeout=30)
    return d["token"]


def _http_err_note(e: urllib.error.HTTPError) -> str:
    try:
        body = json.load(e)
        det = body.get("detail")
        msg = det.get("message", "") if isinstance(det, dict) else str(body)
    except Exception:
        msg = str(e)
    if "budget_exceeded" in msg or "budget" in msg.lower():
        return "❌ 模型配额耗尽（budget_exceeded）——等配额恢复或充值后再跑（非代码问题）"
    if e.code == 503:
        return "❌ 服务暂时不可用——查后端日志 /tmp/backend.log（常见：Pateway 模型配额耗尽或 LLM 熔断）"
    return f"❌ 请求失败（{e.code}）：{msg}"


def _fmt_answer(d: dict, max_len: int = 1200) -> str:
    parts = []
    plan = d.get("plan")
    if plan:
        days = plan.get("days") or []
        parts.append(f"**summary**：{plan.get('summary', '')}")
        for day in days:
            acts = day.get("activities") or []
            acts_txt = "、".join(acts) if isinstance(acts, list) else acts
            parts.append(f"- {day.get('date')}｜{day.get('transport') or '—'}｜{day.get('hotel') or '—'}｜{acts_txt}")
        if plan.get("reasons"):
            parts.append("**理由**：" + "；".join(plan["reasons"]))
    answer = d.get("answer") or ""
    if answer:
        parts.append(answer[:max_len])
    return "\n\n".join(parts) if parts else "(空响应)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="demo/preview.md")
    args = ap.parse_args()

    print("① 检查服务健康…")
    try:
        with urllib.request.urlopen(BASE + "/livez", timeout=10) as resp:
            resp.read()
    except Exception as e:
        print(f"   后端未启动（{e}）。先启动：uv run python -m xiao_wen.webapp")
        return 1
    print("   服务在线 ✓")

    print("② 登录 tester…")
    try:
        token = _login()
        print("   登录成功 ✓")
    except Exception as e:
        print(f"   登录失败：{e}")
        return 1

    lines = [
        "# 晓问 · 演示预演报告",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}｜环境：本地 8000/5173｜账号：tester",
        "",
        "| # | 案例 | 意图 | 状态 |",
        "|---|------|------|------|",
    ]
    rows = []

    print(f"③ 依次执行 {len(CASES)} 个演示案例…")
    for i, (name, prompt) in enumerate(CASES, 1):
        print(f"   [{i}/{len(CASES)}] {name}…", end="", flush=True)
        conv = f"demo-{i:02d}-{int(time.time())}"
        try:
            d = _post("/api/chat", {"user_input": prompt, "conversation_id": conv}, token=token, timeout=150)
        except urllib.error.HTTPError as e:
            note = _http_err_note(e)
            print(f" {note.split('——')[0]}")
            rows.append((i, name, "?", note))
            continue
        except Exception as e:
            print(f" 异常：{e}")
            rows.append((i, name, "?", f"❌ 网络/超时：{e}"))
            continue
        status = "✅" if d.get("answer") or d.get("plan") else "⚠️"
        if isinstance(d.get("detail"), dict):
            status = "❌"
        intent = d.get("intent") or ((d.get("plan") and "行程规划") or "—")
        print(f" {status} intent={intent}")
        rows.append((i, name, intent, status))
        lines.append(
            f"\n---\n\n## 案例 {i}：{name}\n\n"
            f"**提示词**：\n\n> {prompt}\n\n"
            f"**意图**：`{intent}`\n\n"
            f"**晓问回答**：\n\n{_fmt_answer(d)}\n"
        )

    for i, name, intent, status in rows:
        lines.append(f"| {i} | {name} | `{intent}` | {status} |")
    body = "\n".join(lines) + "\n"

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"\n④ 报告已生成：{args.out}（投屏 / 或直接打开前端 5173 现场演示）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
