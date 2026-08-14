# ruff: noqa: E402 —— 插件被注册中心以文件路径 exec_module 加载（懒加载哨兵 print 在 import 前）
"""插件：差旅统计（动态发现演示：主管无需任何改动自动认识新意图）

聚合逻辑抽到 src/xiao_wen/stats.py 共享（与 webapp /api/stats 单一实现）；
本文件只保留插件契约：元数据 + run() 概要文本（页面负责完整画像展示）。
"""

# 懒加载哨兵
print("  ⚠️ [stats] 模块已执行（懒加载触发）")

import os
import sys

# 插件被注册中心以文件路径 exec_module 加载，需自行把 src/ 加入搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from xiao_wen.stats import compute

# ---- 插件元数据 ----
INTENT = "差旅统计"
DESCRIPTION = (
    "汇总统计历史出差的画像数据（出差次数、总天数、年度趋势、常去城市排名）"
    "——只做统计汇总，不查单次行程明细（明细归历史查询），不含花费/金额统计；"
    "回答给概要，完整画像展示在记忆面板"
)


def run(state: dict) -> dict:
    """统一子 Agent 接口：概要文本 + 结构化 stats（聊天里渲染画像卡片）"""
    s = compute(state.get("session_id", "default"))
    if not s["has_data"]:
        return {"answer": "📭 暂无历史行程记录", "stats": s}
    lines = [f"📊 差旅画像：共 {s['trips']} 次行程"]
    if s["total_days"]:
        lines.append(f"  累计出差 {s['total_days']} 天，平均每次 {s['avg_days']} 天")
    if s["years"]:
        trend = "、".join(f"{y['year']} 年 {y['count']} 次" for y in s["years"])
        lines.append(f"  年度分布：{trend}")
    lines.append("")
    lines += [f"  · {c['city']} ×{c['count']} 次" for c in s["top_cities"]]
    if s["skipped_days"]:
        lines.append(f"\n（{s['skipped_days']} 条旧记录缺天数，未计入天数统计）")
    return {"answer": "\n".join(lines), "stats": s}
