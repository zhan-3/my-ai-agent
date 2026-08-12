# ruff: noqa: E402 —— 插件被注册中心以文件路径 exec_module 加载（懒加载哨兵 print 在 import 前）
"""插件：差旅统计（★新功能——演示「动态发现」：主管无需任何改动自动认识新意图）"""

# 懒加载哨兵
print("  ⚠️ [stats] 模块已执行（懒加载触发）")

import os
import sys
from collections import Counter

# 插件被注册中心以文件路径 exec_module 加载，需自行把 src/ 加入搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from xiao_wen.memory import get_itineraries

# ---- 插件元数据 ----
INTENT = "差旅统计"
DESCRIPTION = "统计历史出差的目的地、出差次数、常用城市"


def run(state: dict) -> dict:
    """统一子 Agent 接口：读长期记忆的历史行程做统计"""
    its = get_itineraries()
    if not its:
        return {"answer": "📭 暂无历史行程记录"}
    dests = Counter(i.get("to_city", "未知") for i in its if i.get("to_city") not in ("待定", "未知"))
    trips = len(its)
    top = dests.most_common(5)
    lines = [f"📊 差旅统计：共 {trips} 次行程", ""]
    lines += [f"  · {city} ×{n} 次" for city, n in top]
    lines.append("\n（数据来自长期记忆：data/memory.json）")
    return {"answer": "\n".join(lines)}
