"""交付冒烟：加载 xiao_wen.system 完整系统，跑 3 类代表案例 + 边界（不碰真实记忆）

用法：
  uv run python scripts/smoke.py               # 完整冒烟（真 LLM，约 30-60s）
  uv run python scripts/smoke.py --import-only # 只验证模块可加载（离线自检用）
"""
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

# 冒烟不碰真实记忆：把记忆重定向到临时文件（memory 每次读文件，替换路径即生效）
from xiao_wen import memory as ms  # noqa: E402
ms.MEMORY_PATH = Path(tempfile.mkdtemp()) / "memory.json"

from xiao_wen import system as sys_mod  # noqa: E402

if "--import-only" in sys.argv:
    print("✓ xiao_wen.system 完整系统可加载（离线自检）")
    sys.exit(0)

CASES = [
    ("帮我规划10月8日从上海去北京开会4天的行程", "行程规划"),
    ("出差住宿标准是什么", "知识问答"),
    ("北京今天天气怎么样", "联网查询"),
    ("这个暑假去哪里玩", "其他"),          # 产品边界
]
print("▶ 演示冒烟（真 LLM）")
for text, expected in CASES:
    recent = ms.format_recent_messages(6)
    r = sys_mod.app.invoke(
        {"messages": [("human", text)], "user_input": text, "recent": recent})
    assert r["intent"] == expected, f"{text}: 意图 {r['intent']} ≠ {expected}"
    assert r["answer"].strip(), f"{text}: 回答为空"
    ms.add_message("user", text)
    ms.add_message("assistant", r["answer"])
    print(f"  ✓ {expected}: {r['answer'][:44]}")
print("✓ 冒烟通过")
