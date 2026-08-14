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
DESCRIPTION = (
    "汇总统计历史出差的画像数据（出差次数、总天数、年度趋势、常去城市排名）"
    "——只做统计汇总，不查单次行程明细（如某次住哪、某城市住宿记录，明细归历史查询）"
)


def run(state: dict) -> dict:
    """统一子 Agent 接口：读长期记忆的历史行程做差旅画像（按会话隔离）

    数据源：facts 里的 to_city / start_date / duration_days（TripRequest 强制字段，
    旧记录可能缺天数——统计时跳过并在输出诚实标注）。
    """
    its = get_itineraries(session_id=state.get("session_id", "default"))
    if not its:
        return {"answer": "📭 暂无历史行程记录"}

    dests = Counter(i.get("to_city", "未知") for i in its if i.get("to_city") not in ("待定", "未知"))
    top = dests.most_common(5)
    trips = len(its)

    # 天数统计：仅计入带 duration_days 的行程（旧数据缺失则跳过）
    days = [int(i["duration_days"]) for i in its if isinstance(i.get("duration_days"), int)]
    total_days, avg_days = (sum(days), round(sum(days) / len(days), 1)) if days else (0, 0)

    # 年度趋势：start_date 前 4 位分组
    years = Counter(i.get("start_date", "")[:4] for i in its if i.get("start_date", "")[:4].isdigit())

    lines = [f"📊 差旅画像：共 {trips} 次行程"]
    if total_days:
        lines.append(f"  累计出差 {total_days} 天，平均每次 {avg_days} 天")
    if years:
        trend = "、".join(f"{y} 年 {n} 次" for y, n in sorted(years.items()))
        lines.append(f"  年度分布：{trend}")
    lines.append("")
    lines += [f"  · {city} ×{n} 次" for city, n in top]
    if days and len(days) < trips:
        lines.append(f"\n（{trips - len(days)} 条旧记录缺天数，未计入天数统计）")
    lines.append("\n（数据来自长期记忆，按会话隔离）")
    return {"answer": "\n".join(lines)}
