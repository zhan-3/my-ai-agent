"""会话循环测试：假图 + 临时记忆，测循环四动作（读 recent → 注入 → invoke → 写回两轮）

记忆隔离由 conftest 自动夹具提供（MEMORY_PATH 指向 tmp）。
"""

import pytest

from xiao_wen import memory as memory_store
from xiao_wen.session import ChatResult, chat


class FakeGraph:
    def __init__(self, answer="答", intent="其他", reason="测试"):
        self.answer = answer
        self.intent = intent
        self.reason = reason
        self.calls = []

    def invoke(self, state):
        self.calls.append(state)
        return {"answer": self.answer, "intent": self.intent, "reason": self.reason}


def test_chat_loop_four_actions():
    """读 recent → 注入 → invoke → 写回两轮"""
    graph = FakeGraph()
    memory_store.add_message("user", "上一轮")
    memory_store.add_message("assistant", "上一轮回答")

    r = chat("新问题", graph=graph)

    assert isinstance(r, ChatResult)
    assert r.answer == "答" and r.intent == "其他" and r.reason == "测试"
    assert r.plan is None, "图未产出 plan 时 ChatResult.plan 应为 None"
    # 注入的 recent 包含历史
    assert "上一轮" in graph.calls[0]["recent"]
    assert graph.calls[0]["user_input"] == "新问题"
    # 写回两轮
    msgs = memory_store.get_recent_messages(6)
    assert [m["role"] for m in msgs[-2:]] == ["user", "assistant"]
    assert [m["content"] for m in msgs[-2:]] == ["新问题", "答"]


def test_chat_propagates_structured_plan():
    """图产出结构化 plan → ChatResult.plan 原样透传（slice 1：前端数据驱动的数据源）"""
    plan = {
        "summary": "北京出差 4 天",
        "reasons": ["按差旅标准选住宿"],
        "date_is_vague": False,
        "days": [{"date": "2026-10-08", "transport": "高铁 G1", "hotel": "汉庭", "activities": ["开会"], "notes": ""}],
    }

    class PlanGraph:
        def invoke(self, state):
            return {"answer": "行程如下", "intent": "行程规划", "reason": "r", "plan": plan}

    r = chat("规划行程", graph=PlanGraph())
    assert r.plan == plan


def test_stream_chat_emits_stages_then_done():
    """流式会话：阶段事件（start→intent→working→done）+ 最终 done（含 plan）；记忆写回两轮"""
    import asyncio

    from xiao_wen.session import stream_chat

    plan = {"summary": "北京出差", "days": [], "reasons": [], "date_is_vague": False}
    events = [
        ("on_chain_start", "classify_intent", None),
        ("on_chain_stream", "classify_intent", {"intent": "行程规划", "reason": "r"}),
        ("on_chain_end", "classify_intent", None),
        ("on_chain_start", "行程规划", None),
        ("on_chain_stream", "行程规划", {"answer": "行程如下", "plan": plan}),
        ("on_chain_end", "行程规划", None),
    ]

    class FakeStreamGraph:
        async def astream_events(self, state, **kwargs):
            assert kwargs.get("version") == "v2"
            assert kwargs.get("stream_mode") == "values"
            for etype, node, chunk in events:
                yield {
                    "event": etype,
                    "name": node,
                    "metadata": {"langgraph_node": node},
                    "data": {"chunk": chunk},
                }

    out = []

    async def run():
        async for ev in stream_chat("规划行程", graph=FakeStreamGraph()):
            out.append(ev)

    asyncio.run(run())

    assert out[0] == {"type": "stage", "status": "start"}
    stages = [(e.get("status"), e.get("intent")) for e in out if e["type"] == "stage"]
    assert ("intent", "行程规划") in stages  # 意图已解析
    assert ("working", "行程规划") in stages
    assert ("done", "行程规划") in stages
    assert ("working", "classify_intent") not in stages, "内部节点不暴露为阶段"
    done = out[-1]
    assert done["type"] == "done"
    assert done["answer"] == "行程如下" and done["intent"] == "行程规划"
    assert done["plan"] == plan  # 契约层验证后输出 dict（与 POST /api/chat 响应体一致）
    # 记忆写回两轮（与 chat() 一致）
    msgs = memory_store.get_recent_messages(6)
    assert [m["content"] for m in msgs[-2:]] == ["规划行程", "行程如下"]


def test_stream_chat_filters_nested_chain_events():
    """流式会话：嵌套链事件（name != 节点名）被过滤，只认节点自身事件"""
    import asyncio

    from xiao_wen.session import stream_chat

    events: list[dict] = [
        {"event": "on_chain_start", "name": "行程规划"},
        {"event": "on_chain_start", "name": "RunnableLambda"},  # 嵌套链（应被过滤）
        {"event": "on_chain_end", "name": "RunnableLambda"},
        {
            "event": "on_chain_stream",
            "name": "行程规划",
            "chunk": {"answer": "答", "intent": "行程规划", "reason": "r"},
        },
        {"event": "on_chain_end", "name": "行程规划"},
    ]

    class FakeGraph:
        async def astream_events(self, state, **kwargs):
            for ev in events:
                yield {
                    "event": ev["event"],
                    "name": ev["name"],
                    "metadata": {"langgraph_node": "行程规划"},
                    "data": {"chunk": ev.get("chunk")},
                }

    out = []

    async def run():
        async for ev in stream_chat("hi", graph=FakeGraph()):
            out.append(ev)

    asyncio.run(run())
    # 嵌套链事件不产生重复 working/done
    working = [e for e in out if e.get("status") == "working"]
    done_stages = [e for e in out if e.get("status") == "done" and e.get("type") == "stage"]
    assert len(working) == 1 and len(done_stages) == 1
    assert out[-1]["type"] == "done" and out[-1]["answer"] == "答"


def test_stage_event_mapping():
    """节点名 → 阶段事件：p_ 并行分支剥前缀、merge 占位、classify 隐藏（内部节点）"""
    from xiao_wen.session import _stage_event

    assert _stage_event("p_行程规划", "working") == {"type": "stage", "status": "working", "intent": "行程规划"}
    assert _stage_event("merge", "done") == {"type": "stage", "status": "done", "intent": "__merge__"}
    assert _stage_event("classify_intent", "working") is None
    assert _stage_event("偏好记录", "working") == {"type": "stage", "status": "working", "intent": "偏好记录"}


def test_stream_chat_error_yields_error_event():
    """流式会话：图异常 → error 事件而非中断（LLM 熔断/网络降级）"""
    import asyncio

    from xiao_wen.session import stream_chat

    class BoomGraph:
        async def astream_events(self, state, **kwargs):
            raise RuntimeError("LLM 挂了")

    out = []

    async def run():
        async for ev in stream_chat("hi", graph=BoomGraph()):
            out.append(ev)

    asyncio.run(run())
    assert out[0]["type"] == "stage"
    assert out[-1]["type"] == "error"
    assert "稍后再试" in out[-1]["message"]
    # 异常时不写回记忆
    assert memory_store.get_recent_messages(6) == []


def test_chat_propagates_exceptions():
    class BoomGraph:
        def invoke(self, state):
            raise RuntimeError("LLM 挂了")

    with pytest.raises(RuntimeError, match="LLM 挂了"):
        chat("x", graph=BoomGraph())


def test_chat_uses_injected_store():
    calls = []

    class FakeStore:
        def format_recent_messages(self, n, *, session_id="default"):
            return "无历史"

        def add_message(self, role, content, *, session_id="default"):
            calls.append((role, content, session_id))

    graph = FakeGraph()
    r = chat("hi", session_id="会话A", graph=graph, store=FakeStore())
    assert r.answer == "答"
    assert calls == [("user", "hi", "会话A"), ("assistant", "答", "会话A")]
    assert graph.calls[0]["recent"] == "无历史"


def test_chat_default_graph_is_parallel_supervisor(monkeypatch):
    """默认图 = 图工厂的调度图（parallel=True）：产品 hot path 并行能力接线（Q1/Q6a）"""
    import xiao_wen.graph_builder as gb

    seen = {}

    class FakeGraph:
        def invoke(self, state):
            seen["state"] = state
            return {"answer": "答", "intent": "其他", "reason": "默认图"}

    def fake_build(parallel=False):
        seen["parallel"] = parallel
        return FakeGraph()

    monkeypatch.setattr(gb, "build_supervisor_graph", fake_build)
    r = chat("hi")
    assert r.answer == "答"
    assert seen["parallel"] is True, "默认图应为调度图（多意图并行）"
    assert seen["state"]["recent"] is not None


def test_chat_session_isolation_with_fake_graph():
    """会话隔离验收（无 LLM）：A 写记忆 → B 读不到；State 携带 session_id 到图"""
    from xiao_wen import memory as memory_store

    captured = {}

    class RecGraph:
        def invoke(self, state):
            captured["session_id"] = state.get("session_id")
            captured["recent"] = state["recent"]
            return {"answer": "答", "intent": "其他", "reason": "测试"}

    chat("A的第一个问题", session_id="会话A", graph=RecGraph())
    chat("A的第二个问题", session_id="会话A", graph=RecGraph())
    chat("B的问题", session_id="会话B", graph=RecGraph())

    # State 携带 session_id（产品路径：图内 agent 可感知会话）
    assert captured["session_id"] == "会话B"
    # A 的记忆有 A 的两轮（2 轮 × 用户/助手 2 条）；B 只有 B 自己的
    msgs_a = memory_store.get_recent_messages(6, session_id="会话A")
    msgs_b = memory_store.get_recent_messages(6, session_id="会话B")
    assert [m["content"] for m in msgs_a] == ["A的第一个问题", "答", "A的第二个问题", "答"]
    assert [m["content"] for m in msgs_b] == ["B的问题", "答"]
    assert memory_store.get_recent_messages(6, session_id="default") == []


def test_agents_use_state_session_id(monkeypatch):
    """preference/history agent 从 State 取 session_id 写入对应会话（无 LLM：短路模型）"""
    from xiao_wen.agents import history_agent, preference_agent
    from xiao_wen.memory import get_preferences

    recs = preference_agent.PreferenceList(
        records=[preference_agent.PreferenceRecord(category="常驻城市", content="上海", is_update=True)]
    )

    def _fake_pref_model():
        class M:
            def invoke(self, _):
                return recs

        return M()

    monkeypatch.setattr(preference_agent, "_pref_model", _fake_pref_model)
    out = preference_agent.run({"user_input": "我现在常住上海", "session_id": "会话A"})
    assert "上海" in out["answer"]
    assert [p["content"] for p in get_preferences("常驻城市", session_id="会话A")] == ["上海"]
    assert get_preferences("常驻城市", session_id="会话B") == []

    # history agent：从 State 取 session_id 传给 get_itineraries
    seen = {}

    def fake_get_itineraries(*args, **kwargs):
        seen["session_id"] = kwargs.get("session_id")
        return [
            {
                "to_city": "北京",
                "from_city": "上海",
                "start_date": "2026-05-08",
                "duration_days": 4,
                "summary": "北京出差",
            }
        ]

    monkeypatch.setattr(history_agent, "get_itineraries", fake_get_itineraries)
    out = history_agent.run({"session_id": "会话B"})
    assert seen["session_id"] == "会话B"
    assert "北京" in out["answer"]


def test_history_agent_filters_by_time(monkeypatch):
    """时空语义（确定性规则）：问历史 → 未来规划不出现；问计划 → 只给未来规划"""
    from xiao_wen.agents import history_agent

    its = [
        {
            "to_city": "北京",
            "from_city": "上海",
            "start_date": "2026-05-08",
            "duration_days": 4,
            "summary": "北京出差（已发生）",
        },
        {
            "to_city": "杭州",
            "from_city": "北京",
            "start_date": "2099-12-01",
            "duration_days": 3,
            "summary": "杭州规划（未发生）",
        },
    ]
    monkeypatch.setattr(history_agent, "get_itineraries", lambda **kw: its)

    hist = history_agent.run({"session_id": "x", "user_input": "我上次出差去哪了"})
    assert "北京" in hist["answer"] and "杭州规划" not in hist["answer"]

    plan = history_agent.run({"session_id": "x", "user_input": "我接下来有什么安排"})
    assert "杭州规划" in plan["answer"] and "北京出差" not in plan["answer"]


def test_preference_agent_records_multiple_preferences(monkeypatch):
    """偏好 agent：一条消息含多个偏好 → 全部写入（如「我喜欢住汉庭，常住上海」→ 住宿 + 常驻城市）"""
    from xiao_wen.agents import preference_agent
    from xiao_wen.memory import get_preferences

    recs = preference_agent.PreferenceList(
        records=[
            preference_agent.PreferenceRecord(category="住宿", content="喜欢住汉庭", is_update=False),
            preference_agent.PreferenceRecord(category="常驻城市", content="上海", is_update=True),
        ]
    )

    def _fake_pref_model():
        class M:
            def invoke(self, _):
                return recs

        return M()

    monkeypatch.setattr(preference_agent, "_pref_model", _fake_pref_model)
    out = preference_agent.run({"user_input": "我喜欢住汉庭，常住上海", "session_id": "会话A"})
    assert "住宿" in out["answer"] and "常驻城市" in out["answer"]
    prefs = get_preferences(session_id="会话A")
    assert {p["category"] for p in prefs} == {"住宿", "常驻城市"}
    assert [p["content"] for p in prefs if p["category"] == "常驻城市"] == ["上海"]


def test_itinerary_agent_passes_session_to_trip_planner(monkeypatch):
    """行程 agent：State 的 session_id 贯穿到 trip_planner 的 add_itinerary（无 LLM：短路模型链）"""
    from xiao_wen import trip_planner
    from xiao_wen.agents import itinerary_agent

    captured = {}

    def fake_add_itinerary(facts, summary, *, session_id="default"):
        captured["session_id"] = session_id
        captured["summary"] = summary
        return {"summary": summary, "ts": "t"}

    monkeypatch.setattr(trip_planner, "add_itinerary", fake_add_itinerary)
    req = trip_planner.TripRequest(
        from_city="上海", to_city="北京", start_date="2026-10-08", duration_days=4, hotel_pref="无", budget_pref="中等"
    )
    plan = trip_planner.ItineraryPlan(
        days=[],
        summary="北京出差 4 天",
        reasons=["靠近会场"],
    )

    class FakeExtract:
        def invoke(self, _):
            return req

    class FakePlan:
        def invoke(self, _):
            return plan

    monkeypatch.setattr(trip_planner, "_extract_model", FakeExtract)
    monkeypatch.setattr(trip_planner, "_plan_model", FakePlan)

    out = itinerary_agent.run({"user_input": "我10月8日去北京开会4天", "session_id": "会话A"})
    assert captured["session_id"] == "会话A"  # 行程写进 A 会话
    assert captured["summary"] == "北京出差 4 天"
    assert "北京" in out["answer"]


def test_itinerary_agent_returns_structured_plan(monkeypatch):
    """行程 agent：生成成功 → 返回结构化 plan（slice 1 数据驱动源）；缺项 → plan 为 None"""
    from xiao_wen import trip_planner
    from xiao_wen.agents import itinerary_agent

    req = trip_planner.TripRequest(
        from_city="上海",
        to_city="北京",
        start_date="2026-10-08",
        duration_days=4,
        hotel_pref="无",
        budget_pref="中等",
    )
    plan = trip_planner.ItineraryPlan(
        days=[
            trip_planner.DayPlan(
                date="2026-10-08", transport="高铁 G1", hotel="汉庭", activities=["上午开会"], notes=""
            )
        ],
        summary="北京出差 4 天",
        reasons=["按差旅标准选住宿"],
    )

    class FakeExtract:
        def invoke(self, _):
            return req

    class FakePlan:
        def invoke(self, _):
            return plan

    monkeypatch.setattr(trip_planner, "_extract_model", FakeExtract)
    monkeypatch.setattr(trip_planner, "_plan_model", FakePlan)
    monkeypatch.setattr(
        trip_planner, "add_itinerary", lambda facts, summary, *, session_id="default": {"summary": summary}
    )
    monkeypatch.setattr(itinerary_agent, "get_weather", type("W", (), {"invoke": lambda self, a: "晴"})())

    out = itinerary_agent.run({"user_input": "10月8日去北京开会4天", "session_id": "会话A"})
    assert out["plan"] == {
        **plan.model_dump(),
        "date_is_vague": False,
    }
    assert out["plan"]["days"][0]["transport"] == "高铁 G1"

    # 缺项（NeedsInfo）：plan 为 None，前端走文本回退
    vague_req = trip_planner.TripRequest(
        from_city="上海", to_city="", start_date="", duration_days=0, hotel_pref="无", budget_pref="中等"
    )

    class FakeExtract2:
        def invoke(self, _):
            return vague_req

    monkeypatch.setattr(trip_planner, "_extract_model", FakeExtract2)
    out2 = itinerary_agent.run({"user_input": "帮我规划", "session_id": "会话A"})
    assert out2.get("plan") is None


def test_itinerary_agent_appends_weather_reminder(monkeypatch):
    """行程 agent：生成成功且日期可查 → 答案附加目的地天气提醒（结合行程规划）；天气失败不影响主答案"""
    from xiao_wen import trip_planner
    from xiao_wen.agents import itinerary_agent

    req = trip_planner.TripRequest(
        from_city="上海", to_city="北京", start_date="2026-10-08", duration_days=4, hotel_pref="无", budget_pref="中等"
    )
    plan = trip_planner.ItineraryPlan(days=[], summary="北京出差 4 天", reasons=["靠近会场"])

    class FakeExtract:
        def invoke(self, _):
            return req

    class FakePlan:
        def invoke(self, _):
            return plan

    monkeypatch.setattr(trip_planner, "_extract_model", FakeExtract)
    monkeypatch.setattr(trip_planner, "_plan_model", FakePlan)
    monkeypatch.setattr(
        trip_planner, "add_itinerary", lambda facts, summary, *, session_id="default": {"summary": summary}
    )

    class FakeWeather:
        def invoke(self, args):
            return f"{args['city']} {args['date']} 晴 25°C"

    monkeypatch.setattr(itinerary_agent, "get_weather", FakeWeather())
    out = itinerary_agent.run({"user_input": "10月8日去北京开会4天", "session_id": "会话A"})
    assert "北京出差 4 天" in out["answer"]
    assert "目的地天气提醒" in out["answer"] and "晴" in out["answer"]

    # 天气查询失败（网络/超期）：行程主答案不受影响
    def boom(args):
        raise RuntimeError("网络挂了")

    monkeypatch.setattr(itinerary_agent, "get_weather", boom)
    out2 = itinerary_agent.run({"user_input": "10月8日去北京开会4天", "session_id": "会话A"})
    assert "北京出差 4 天" in out2["answer"]
    assert "目的地天气提醒" not in out2["answer"]


def test_itinerary_agent_confirms_vague_date(monkeypatch):
    """行程 agent：日期表达模糊（如只说了「下周」）→ 生成后明确提示日期是推断的、可调整；具体日期则无提示"""
    from xiao_wen import trip_planner
    from xiao_wen.agents import itinerary_agent

    def run_with(req):
        plan = trip_planner.ItineraryPlan(days=[], summary="杭州出差 3 天", reasons=[])

        class FakeExtract:
            def invoke(self, _):
                return req

        class FakePlan:
            def invoke(self, _):
                return plan

        monkeypatch.setattr(trip_planner, "_extract_model", FakeExtract)
        monkeypatch.setattr(trip_planner, "_plan_model", FakePlan)
        monkeypatch.setattr(
            trip_planner, "add_itinerary", lambda facts, summary, *, session_id="default": {"summary": summary}
        )
        monkeypatch.setattr(itinerary_agent, "get_weather", type("W", (), {"invoke": lambda self, a: "晴"})())
        return itinerary_agent.run({"user_input": "x", "session_id": "会话A"})["answer"]

    vague = trip_planner.TripRequest(
        from_city="北京",
        to_city="杭州",
        start_date="2026-08-17",
        duration_days=3,
        hotel_pref="无",
        budget_pref="中等",
        date_is_vague=True,
    )
    out_vague = run_with(vague)
    assert "按 2026-08-17 开始安排" in out_vague and "重新排" in out_vague

    exact = trip_planner.TripRequest(
        from_city="北京", to_city="杭州", start_date="2026-08-17", duration_days=3, hotel_pref="无", budget_pref="中等"
    )
    out_exact = run_with(exact)
    assert "重新排" not in out_exact


def test_preference_agent_skips_questions_no_garbage(monkeypatch):
    """疑问句（「我常住哪里」）→ 提取器返回空 records → 不写任何记忆、给引导提示"""
    from xiao_wen.agents import preference_agent
    from xiao_wen.memory import get_preferences

    recs = preference_agent.PreferenceList(records=[])

    def _empty_model():
        class M:
            def invoke(self, _):
                return recs

        return M()

    monkeypatch.setattr(preference_agent, "_pref_model", _empty_model)
    out = preference_agent.run({"user_input": "我常住哪里", "session_id": "会话C"})
    assert "询问" in out["answer"]
    assert get_preferences(session_id="会话C") == [], "疑问句绝不能写进长期记忆"


def test_preference_agent_retries_on_parse_failure(monkeypatch):
    """BUG-005：json_mode 结构化输出偶发截断/非法 JSON → 同一输入重试，LLM 自愈"""
    from xiao_wen.agents import preference_agent

    good = preference_agent.PreferenceList(
        records=[preference_agent.PreferenceRecord(category="住宿", content="喜欢住全季", is_update=False)]
    )

    class _FlakyModel:
        def __init__(self, fail_times: int = 1):
            self.calls = 0
            self.fail_times = fail_times

        def invoke(self, _):
            self.calls += 1
            if self.calls <= self.fail_times:
                raise ValueError('Failed to parse PreferenceList from completion {"records": ["截断"]}')
            return good

    flaky = _FlakyModel(fail_times=1)
    monkeypatch.setattr(preference_agent, "_pref_model", lambda: flaky)
    out = preference_agent.run({"user_input": "我喜欢住全季", "session_id": "会话F"})
    assert "全季" in out["answer"]
    assert flaky.calls == 2, "首次解析失败应自动重试一次"

    # 重试耗尽仍失败（重试 2 次全失败，共 3 次调用）→ 向上抛（web 层稳定性兜底），不静默
    bad = _FlakyModel(fail_times=99)
    monkeypatch.setattr(preference_agent, "_pref_model", lambda: bad)
    with pytest.raises(ValueError):
        preference_agent.run({"user_input": "我喜欢住全季", "session_id": "会话F"})
    assert bad.calls == 3, "重试次数应为 2（共 3 次调用）"


def test_history_agent_shows_preferences(monkeypatch):
    """记忆查询（如「我常住哪里」）→ 历史查询 Agent 输出记忆偏好（含常驻城市）"""
    from xiao_wen.agents import history_agent
    from xiao_wen.memory import add_or_update_preference

    add_or_update_preference("常驻城市", "上海", True, session_id="会话D")
    out = history_agent.run({"session_id": "会话D"})
    assert "常驻城市 上海" in out["answer"]


def test_history_agent_answers_what_was_asked(monkeypatch):
    """意图对齐：问「上次的行程」只答行程（无则明确空态），不无差别倒出偏好"""
    from xiao_wen.agents import history_agent
    from xiao_wen.memory import add_or_update_preference

    add_or_update_preference("餐饮", "不吃辣", True, session_id="会话E")
    add_or_update_preference("住宿", "喜欢安静", True, session_id="会话E")

    # 行程向问题：只有偏好没有行程 → 明确「暂无历史行程」，不列偏好（原实现答非所问）
    out = history_agent.run({"user_input": "我上次的行程是什么", "session_id": "会话E"})
    assert "暂无历史行程记录" in out["answer"]
    assert "不吃辣" not in out["answer"]

    # 偏好向问题：只答偏好
    out2 = history_agent.run({"user_input": "我的饮食偏好是什么", "session_id": "会话E"})
    assert "不吃辣" in out2["answer"]
    assert "暂无历史行程" not in out2["answer"]

    # 综合查询（无关键词）：全答，且空态也说明
    out3 = history_agent.run({"session_id": "会话E"})
    assert "不吃辣" in out3["answer"] and "暂无历史行程记录" in out3["answer"]


def test_history_agent_followup_never_empty(monkeypatch):
    """BUG-001：筛选/追问句（无行程/偏好关键词）绝不返回空串，给明确空态文案"""
    from xiao_wen.agents import history_agent

    # 无任何记录的会话：原实现这些输入会得到 parts=[] → 空回复
    followups = [
        "还是没有杭州的记录，你再核实一下，我确定去的是杭州住民宿。",
        "具体日期我记不清了，只记得在杭州住的是民宿，能帮我找出来吗？",
        "对，杭州那次就是民宿，你帮我定位一下具体日期和地点。",
        "我再按民宿筛选一次历史消费，单独查杭州的订单。",
        "对了，我想起来杭州那次住的民宿好像在西湖区，你按这个范围再筛一下。",
        "那次西湖区的民宿，我记不清具体日期了，只记得是工作日，能帮我查查入住时间吗？",
    ]
    for q in followups:
        out = history_agent.run({"user_input": q, "session_id": "会话F"})
        assert out["answer"].strip(), f"BUG-001 空回复：{q}"
        assert "未找到" in out["answer"] or "暂无" in out["answer"], f"缺空态文案：{q}"


def test_history_agent_filters_by_city(monkeypatch):
    """BUG-001：提到城市时按城市过滤行程，未命中给带城市名的引导空态"""
    from xiao_wen.agents import history_agent
    from xiao_wen.memory import add_itinerary

    add_itinerary(
        {"from_city": "上海", "to_city": "武汉", "start_date": "2026-10-08", "duration_days": 2},
        "武汉出差总结",
        session_id="会话G",
    )
    add_itinerary(
        {"from_city": "上海", "to_city": "杭州", "start_date": "2026-09-01", "duration_days": 3},
        "杭州住民宿见客户",
        session_id="会话G",
    )

    # 查杭州 → 只命中杭州那条，不把武汉的倒出来
    out = history_agent.run({"user_input": "帮我单独查一下杭州的出差记录", "session_id": "会话G"})
    assert "杭州" in out["answer"] and "武汉" not in out["answer"]

    # 查没有的城市 → 带城市名的引导空态，而不是全部倒出
    out2 = history_agent.run({"user_input": "有没有广州的出差记录", "session_id": "会话G"})
    assert "未找到广州的记录" in out2["answer"]


def test_stream_chat_plan_from_on_chain_end_output():
    """普通函数节点不产生 stream chunk——plan 写在 on_chain_end 的 output 里，也必须捕获"""
    import asyncio

    from xiao_wen.session import stream_chat

    plan = {"summary": "广州出差", "days": [], "reasons": [], "date_is_vague": False}
    events = [
        ("on_chain_start", "classify_intent", None, None),
        ("on_chain_stream", "classify_intent", {"intent": "行程规划", "reason": "r"}, None),
        ("on_chain_end", "classify_intent", None, None),
        ("on_chain_start", "行程规划", None, None),
        # 无 on_chain_stream：行程 agent 是普通函数节点，只产出 on_chain_end.output
        ("on_chain_end", "行程规划", None, {"answer": "行程如下", "plan": plan}),
    ]

    class FakeStreamGraph:
        async def astream_events(self, state, **kwargs):
            for etype, node, chunk, output in events:
                yield {
                    "event": etype,
                    "name": node,
                    "metadata": {"langgraph_node": node},
                    "data": {"chunk": chunk, "output": output},
                }

    out = []

    async def run():
        async for ev in stream_chat("规划行程", graph=FakeStreamGraph()):
            out.append(ev)

    asyncio.run(run())

    done = out[-1]
    assert done["type"] == "done"
    assert done["answer"] == "行程如下"
    assert done["plan"] == plan  # on_chain_end output 捕获后同样输出 dict


def test_chat_falls_back_on_empty_answer(monkeypatch):
    """防御：Agent 返回空/缺失 answer → 兜底文案，不向前端吐空串"""
    from xiao_wen import session as sess

    class FakeGraph:
        def invoke(self, state):
            return {"answer": "", "intent": "其他", "reason": "r"}

    store = memory_store
    r = sess.chat("你好", graph=FakeGraph(), store=store)
    assert r.answer == sess._FALLBACK_ANSWER
    msgs = store.get_recent_messages(6)
    assert msgs[-1]["content"] == sess._FALLBACK_ANSWER


def test_stream_chat_error_midstream_yields_error_and_skips_writeback():
    """SSE 错误路径：流中途炸（已发部分阶段事件后异常）→ error 收尾，不中断、无 done、不写回记忆"""
    import asyncio

    from xiao_wen.session import stream_chat

    class BoomMidGraph:
        async def astream_events(self, state, **kwargs):
            yield {
                "event": "on_chain_start",
                "name": "classify_intent",
                "metadata": {"langgraph_node": "classify_intent"},
                "data": {},
            }
            yield {
                "event": "on_chain_start",
                "name": "行程规划",
                "metadata": {"langgraph_node": "行程规划"},
                "data": {},
            }
            raise RuntimeError("LLM 熔断")

    out = []

    async def run():
        async for ev in stream_chat("规划行程", graph=BoomMidGraph()):
            out.append(ev)

    asyncio.run(run())
    assert out[0]["type"] == "stage"
    assert out[-1]["type"] == "error" and "稍后再试" in out[-1]["message"]
    assert all(e["type"] != "done" for e in out), "中途异常不应产出 done"
    assert memory_store.get_recent_messages(6) == [], "异常时不写回记忆"


def test_stream_chat_empty_state_yields_error_not_done():
    """SSE 防御分支：图跑完但没产出任何 state → error 事件（而非假 done 兜底）"""
    import asyncio

    from xiao_wen.session import stream_chat

    class EmptyGraph:
        async def astream_events(self, state, **kwargs):
            yield {
                "event": "on_chain_start",
                "name": "知识问答",
                "metadata": {"langgraph_node": "知识问答"},
                "data": {},
            }
            yield {
                "event": "on_chain_end",
                "name": "知识问答",
                "metadata": {"langgraph_node": "知识问答"},
                "data": {"output": None},
            }

    out = []

    async def run():
        async for ev in stream_chat("住宿标准", graph=EmptyGraph()):
            out.append(ev)

    asyncio.run(run())
    assert out[-1]["type"] == "error"
    assert all(e["type"] != "done" for e in out)
    assert memory_store.get_recent_messages(6) == []
