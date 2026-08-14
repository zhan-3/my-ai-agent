"""差旅统计聚合：确定性纯函数，零 LLM。

供两处共享（单一实现，避免复制）：
- plugins/stats.py 的 run()：插件契约（识别为「差旅统计」意图时生成概要文本）
- webapp /api/stats：页面直接拉取画像数据渲染（更快、0 token、所见即所得）

设计判断：差旅统计回答的是「用户自己数据库里的结构化数据」（次数/天数/城市/年度），
不是开放生成——确定性聚合 + 页面展示，LLM 只负责意图识别这一件事。
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Any

from xiao_wen.memory import get_itineraries


def classify(itineraries: list[dict], today: date | None = None) -> dict[str, list[dict]]:
    """行程三态分类（确定性时间规则，零 LLM）：

    - past：已结束（end < today）——真实发生过的历史
    - ongoing：进行中（start <= today <= end）——正在出差
    - upcoming：未来规划（start > today）——用户还没实行，只是计划

    end = start_date + duration_days - 1；缺 start_date → 保守归 past（老记录）；
    缺 duration_days → 视为当天往返（end = start_date）。
    """
    today = today or date.today()
    past: list[dict] = []
    ongoing: list[dict] = []
    upcoming: list[dict] = []
    for it in itineraries:
        raw = str(it.get("start_date", ""))[:10]
        try:
            start = date.fromisoformat(raw)
        except ValueError:
            past.append(it)  # 无日期旧记录：按历史处理，不丢数据
            continue
        dur = it.get("duration_days")
        end = start + timedelta(days=(int(dur) - 1 if isinstance(dur, int) and dur > 0 else 0))
        if end < today:
            past.append(it)
        elif start > today:
            upcoming.append(it)
        else:
            ongoing.append(it)
    return {"past": past, "ongoing": ongoing, "upcoming": upcoming}


def compute(session_id: str = "default", today: date | None = None) -> dict[str, Any]:
    """读长期记忆的历史行程，聚合出差画像（按会话隔离）。

    统计口径：**已发生**（past + ongoing）——未来规划（upcoming）不算「去过/出差过」，
    单独以 upcoming_trips 诚实标注（规划可能没实行，口径与「历史行程」一致）。
    数据源：facts 里的 to_city / start_date / duration_days（TripRequest 强制字段，
    旧记录可能缺天数——统计时跳过并诚实标注 skipped_days）。
    """
    its = get_itineraries(session_id=session_id)
    c = classify(its, today)
    happened = c["past"] + c["ongoing"]
    dests = Counter(i.get("to_city", "未知") for i in happened if i.get("to_city") not in ("待定", "未知"))
    days = [int(i["duration_days"]) for i in happened if isinstance(i.get("duration_days"), int)]
    years = Counter(i.get("start_date", "")[:4] for i in happened if i.get("start_date", "")[:4].isdigit())
    return {
        "has_data": bool(happened),
        "trips": len(happened),
        "total_days": sum(days),
        "avg_days": round(sum(days) / len(days), 1) if days else 0,
        "skipped_days": len(happened) - len(days),
        "top_cities": [{"city": city, "count": n} for city, n in dests.most_common(5)],
        "years": [{"year": y, "count": n} for y, n in sorted(years.items())],
        "upcoming_trips": len(c["upcoming"]),
    }
