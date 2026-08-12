"""多 Agent 机制演示：动态发现 / 渐进式披露 / 懒加载 / 热插拔（真实产品路径）

跑法：uv run python -m xiao_wen.demos.plugin_demo
四幕演示（全部作用于真实主管 xiao_wen.system.app）：
  第1幕 动态发现（渐进式披露）：注册表扫描内置六子 Agent + 外部扩展，
        只读 AST 元数据，不执行任何子 Agent 代码
  第2幕 懒加载：未派发的子 Agent 不加载（sys.modules 为证）；派发才加载（哨兵为证）
  第3幕 热插拔：运行中向 plugins/ 新增子 Agent → 文件层即时感知 → 重建主管图即路由（主管零改动）
  第4幕 外部扩展真实路由：差旅统计（第七意图）在真实 system.app 里被识别并派发
"""
import importlib
import sys
from pathlib import Path

from xiao_wen import system as sys_mod
from xiao_wen.plugin_registry import discover, load_agent

ROOT = Path(__file__).resolve().parents[3]  # src/xiao_wen/demos → 项目根
PLUGIN_DIR = ROOT / "plugins"

if __name__ == "__main__":
    print("=" * 60)
    print("第1幕｜动态发现（渐进式披露）：注册表只读元数据，不执行任何子 Agent 代码")
    manifest = discover()
    for m in manifest:
        tag = "内置" if m["source"] == "builtin" else "外部"
        print(f"  🔍 [{tag}] {m['file']:<22} → {m['INTENT']}：{m['DESCRIPTION'][:26]}…")
    print(f"  → 意图词汇表（主管自动认识）：{'、'.join(m['INTENT'] for m in manifest)}")
    print("  → 无任何『模块已执行』日志 = AST 渐进披露生效，意图识别阶段零加载\n")

    print("=" * 60)
    print("第2幕｜懒加载：未派发的子 Agent 不加载，派发才加载")
    print("  调用行程规划前，是否已加载 web_agent？",
          "xiao_wen.agents.web_agent" in sys.modules)
    load_agent("行程规划")  # 内置：import_module
    print("  调用行程规划后，是否已加载 web_agent？",
          "xiao_wen.agents.web_agent" in sys.modules)
    print("  加载外部扩展 stats（哨兵日志『[stats] 模块已执行』证明此时才执行）：")
    load_agent("差旅统计")
    print("  → 懒加载生效：未使用的子 Agent 不加载（原要求：未使用的模块不加载）\n")

    print("=" * 60)
    print("第3幕｜热插拔：运行中新增子 Agent → 文件层即时感知 → 重建主管即认识新意图")
    new_agent = '''"""外部子 Agent：差旅总结（运行中热插拔加入）"""
print("  ⚠️ [summary] 模块已执行（懒加载触发）")

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from xiao_wen.memory import get_itineraries, get_preferences

INTENT = "差旅总结"
DESCRIPTION = "汇总差旅次数、常用目的地、已知偏好习惯"

def run(state: dict) -> dict:
    its = get_itineraries()
    prefs = get_preferences()
    pref_txt = "；".join(f"{p['category']}:{p['content']}" for p in prefs) or "无"
    n = len(its)
    dests = {i.get("to_city") for i in its if i.get("to_city") not in ("待定", "未知")}
    return {"answer": f"🧳 差旅档案：共 {n} 次行程，去过 {'、'.join(sorted(dests)) or '暂无'}；偏好：{pref_txt}"}
'''
    (PLUGIN_DIR / "summary.py").write_text(new_agent, encoding="utf-8")
    manifest = discover()
    print(f"  → 重新发现，现在 {len(manifest)} 个意图："
          f"{'、'.join(m['INTENT'] for m in manifest)}")
    # 主管零改动：重建主管图（manifest 重新扫描 + 词汇表注入），路由新意图
    importlib.reload(sys_mod)
    from xiao_wen.session import chat
    q = "帮我总结一下我的差旅情况"
    r = chat(q)
    print(f"  用户：{q}")
    print(f"  意图：{r.intent}（{r.reason}）")
    print(f"  答复：{r.answer}\n")

    print("=" * 60)
    print("第4幕｜外部扩展真实路由：差旅统计在真实 system.app 里被识别并派发")
    q2 = "统计一下我的出差情况"
    r2 = chat(q2)
    print(f"  用户：{q2}")
    print(f"  意图：{r2.intent}（{r2.reason}）")
    print(f"  答复：{r2.answer}\n")

    # 清理热插拔演示文件（恢复基线：内置六 + 外部 stats）
    (PLUGIN_DIR / "summary.py").unlink()
    importlib.reload(sys_mod)
    print("（已清理热插拔演示文件 summary.py，插件目录恢复基线）")
