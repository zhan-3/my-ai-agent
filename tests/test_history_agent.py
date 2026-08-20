"""历史查询子 Agent 的城市过滤：非白名单城市（如临沂）也必须能按城市筛选。

KNOWN_CITIES 只是「有经纬度坐标的城市」，不是城市全集；历史行程里的
临沂等城市不在坐标表里，但用户问「我去临沂的行程」时必须能过滤命中。
"""

from xiao_wen.agents import history_agent
from xiao_wen.agents.history_agent import _itinerary_matches, _mentioned_cities


def test_mentioned_cities_includes_non_whitelist_history_city():
    q = "我去临沂的行程"
    its = [{"from_city": "临沂", "to_city": "北京"}]
    assert "临沂" in _mentioned_cities(q, its)


def test_mentioned_cities_still_recognizes_whitelist():
    assert "北京" in _mentioned_cities("去北京的行程", [])
    assert "哈尔滨" in _mentioned_cities("哈尔滨的出差记录", [])


def test_mentioned_cities_ignores_placeholders():
    its = [{"from_city": "待定", "to_city": "出差"}]
    assert _mentioned_cities("出差的行程", its) == []


def test_itinerary_matches_filters_by_non_whitelist_city():
    its = [
        {"from_city": "临沂", "to_city": "北京"},
        {"from_city": "上海", "to_city": "广州"},
    ]
    cities = _mentioned_cities("我去临沂的行程", its)
    matched = [it for it in its if _itinerary_matches(it, cities)]
    assert matched == [{"from_city": "临沂", "to_city": "北京"}]


def test_mentioned_cities_dedupes_and_orders_whitelist_first():
    q = "北京和临沂的行程"
    its = [{"from_city": "临沂", "to_city": "北京"}]
    cities = _mentioned_cities(q, its)
    assert cities.index("北京") < cities.index("临沂")


# ---- run() 主路径（确定性：mock 记忆层，真实 stats.classify 时间规则） ----


def _state(q: str) -> dict:
    return {"user_input": q, "user_id": "u1"}


def _seed(monkeypatch, *, its=None, prefs=None) -> None:
    # history_agent 是模块级 from xiao_wen.memory import ...，须替换模块内绑定
    monkeypatch.setattr(history_agent, "get_itineraries", lambda **kw: its or [])
    monkeypatch.setattr(history_agent, "get_preferences", lambda **kw: prefs or [])


_IT = {
    "start_date": "2026-08-01",
    "from_city": "上海",
    "to_city": "北京",
    "duration_days": 3,
    "summary": "参加行业峰会",
}


def test_run_history_returns_itineraries_and_structure(monkeypatch):
    """行程向：历史行程 → 话术 + 结构化 history（status=历史）。"""
    _seed(monkeypatch, its=[_IT])
    result = history_agent.run(_state("我上次的行程是什么"))
    assert "🗂️ 历史行程：" in result["answer"]
    assert "上海→北京" in result["answer"]
    assert result["history"] == {
        "itineraries": [
            {
                "start_date": "2026-08-01",
                "from_city": "上海",
                "to_city": "北京",
                "duration_days": 3,
                "summary": "参加行业峰会",
                "status": "历史",
            }
        ],
        "preferences": [],
        "direction": "历史",
    }


def test_run_plan_direction_returns_upcoming(monkeypatch):
    """计划向（什么时候出发）→ 已规划行程 + direction=计划。"""
    future = {**_IT, "start_date": "2026-09-01"}
    _seed(monkeypatch, its=[future])
    result = history_agent.run(_state("我接下来的行程安排是什么"))
    assert "📅 已规划的行程：" in result["answer"]
    assert result["history"]["itineraries"][0]["status"] == "已规划"
    assert result["history"]["direction"] == "计划"


def test_run_city_filter_no_match_gives_city_empty_state(monkeypatch):
    """城市过滤未命中 → 带城市名的引导空态（不倒全部行程）。"""
    _seed(monkeypatch, its=[_IT])
    result = history_agent.run(_state("还是没有杭州的记录"))
    assert "📭 未找到杭州的记录" in result["answer"]
    assert "北京" not in result["answer"]
    assert result["history"] is None


def test_run_city_filter_matches_non_whitelist_city(monkeypatch):
    """非白名单城市（临沂）也能按城市过滤命中。"""
    its = [{**_IT, "from_city": "临沂", "to_city": "北京"}]
    _seed(monkeypatch, its=its)
    result = history_agent.run(_state("我去临沂的行程"))
    assert "临沂→北京" in result["answer"]
    assert len(result["history"]["itineraries"]) == 1


def test_run_empty_memory_returns_both_empty_states(monkeypatch):
    """无行程无偏好 → 两条明确空态（绝不空串）。"""
    _seed(monkeypatch, its=[], prefs=[])
    result = history_agent.run(_state(""))
    assert "📭 暂无历史行程记录。" in result["answer"]
    assert "💡 暂无记忆偏好。" in result["answer"]
    assert result["history"] is None


def test_run_preference_query_returns_prefs(monkeypatch):
    """偏好向：只答偏好，不倒行程。"""
    _seed(monkeypatch, its=[_IT], prefs=[{"category": "住宿", "content": "喜欢安静", "ts": "t"}])
    result = history_agent.run(_state("我有什么住宿偏好"))
    assert "💡 记忆偏好：住宿 喜欢安静" in result["answer"]
    assert "行程" not in result["answer"]
    assert result["history"]["preferences"] == [{"category": "住宿", "content": "喜欢安静"}]


def test_run_ongoing_status(monkeypatch):
    """进行中（今天在出差）→ status=进行中。"""
    from datetime import date

    today = date.today()
    ongoing = {
        **_IT,
        "start_date": today.isoformat(),
        "duration_days": 2,
    }
    _seed(monkeypatch, its=[ongoing])
    result = history_agent.run(_state("我的行程记录"))
    assert result["history"]["itineraries"][0]["status"] == "进行中"


def test_run_limits_recent_five(monkeypatch):
    """最多展示最近 5 条（超出截断）。"""
    its = [{**_IT, "start_date": f"2026-07-{i:02d}", "summary": f"行程{i}"} for i in range(1, 8)]
    _seed(monkeypatch, its=its)
    result = history_agent.run(_state("我的出差记录"))
    assert result["answer"].count("· 2026-07") == 5
    assert len(result["history"]["itineraries"]) == 5


# ---- 中性问法（最近有哪些行程）：upcoming 不能丢 ----


def _future_it(start: str, summary: str = "未来会议") -> dict:
    return {**_IT, "start_date": start, "summary": summary}


def test_run_neutral_query_shows_all_three_states(monkeypatch):
    """「最近有哪些行程」→ 中性：历史/进行中/已规划三态全展示，各自标状态。"""
    from datetime import date

    today = date.today()
    its = [
        {**_IT, "start_date": "2026-07-01"},  # 过去 → 历史
        {**_IT, "start_date": today.isoformat(), "duration_days": 2},  # 进行中
        _future_it("2026-09-01"),  # 未来 → 已规划
    ]
    _seed(monkeypatch, its=its)
    result = history_agent.run(_state("我最近有哪些行程"))
    assert "📋 最近行程：" in result["answer"]
    statuses = [it["status"] for it in result["history"]["itineraries"]]
    assert statuses == ["已规划", "进行中", "历史"]  # reversed 后：未来在前
    assert result["history"]["direction"] == "全部"


def test_run_neutral_query_keeps_upcoming_only(monkeypatch):
    """回归：两条未来行程，「最近有哪些行程」必须两条都显示（不能只剩 1 条）。"""
    its = [_future_it("2026-08-26", "杭州出差"), _future_it("2026-08-28", "西安出差")]
    _seed(monkeypatch, its=its)
    result = history_agent.run(_state("我最近有哪些行程"))
    assert "杭州出差" in result["answer"]
    assert "西安出差" in result["answer"]
    assert len(result["history"]["itineraries"]) == 2
    assert all(it["status"] == "已规划" for it in result["history"]["itineraries"])
    assert result["history"]["direction"] == "全部"


def test_run_past_word_limits_to_history(monkeypatch):
    """明确历史词（去过/之前）→ 只查已发生，upcoming 不显示。"""
    its = [_future_it("2026-09-01"), {**_IT, "start_date": "2026-07-01"}]
    _seed(monkeypatch, its=its)
    result = history_agent.run(_state("我上次去过哪些地方"))
    assert "2026-07-01" in result["answer"]
    assert "2026-09-01" not in result["answer"]
    assert result["history"]["direction"] == "历史"
