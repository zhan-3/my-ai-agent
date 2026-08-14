"""差旅统计聚合：确定性纯函数，零 LLM。

供两处共享（单一实现，避免复制）：
- plugins/stats.py 的 run()：插件契约（识别为「差旅统计」意图时生成概要文本）
- webapp /api/stats：页面直接拉取画像数据渲染（更快、0 token、所见即所得）

设计判断：差旅统计回答的是「用户自己数据库里的结构化数据」（次数/天数/城市/年度），
不是开放生成——确定性聚合 + 页面展示，LLM 只负责意图识别这一件事。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from xiao_wen.memory import get_itineraries


def compute(session_id: str = "default") -> dict[str, Any]:
    """读长期记忆的历史行程，聚合出差画像（按会话隔离）。

    数据源：facts 里的 to_city / start_date / duration_days（TripRequest 强制字段，
    旧记录可能缺天数——统计时跳过并诚实标注 skipped_days）。
    """
    its = get_itineraries(session_id=session_id)
    dests = Counter(i.get("to_city", "未知") for i in its if i.get("to_city") not in ("待定", "未知"))
    days = [int(i["duration_days"]) for i in its if isinstance(i.get("duration_days"), int)]
    years = Counter(i.get("start_date", "")[:4] for i in its if i.get("start_date", "")[:4].isdigit())
    return {
        "has_data": bool(its),
        "trips": len(its),
        "total_days": sum(days),
        "avg_days": round(sum(days) / len(days), 1) if days else 0,
        "skipped_days": len(its) - len(days),
        "top_cities": [{"city": city, "count": n} for city, n in dests.most_common(5)],
        "years": [{"year": y, "count": n} for y, n in sorted(years.items())],
    }
