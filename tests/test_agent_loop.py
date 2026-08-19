import time
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from xiao_wen.agent_loop import AgentLoop, LoopLimits, _message_tokens, _provides_origin, _result, _trip_requested


class ScriptedModel:
    def __init__(self, *messages):
        self.messages = list(messages)
        self.inputs = []
        self.tools = None

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages):
        self.inputs.append(list(messages))
        return self.messages.pop(0)


def call(name: str, request: str, call_id: str = "call-1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": {"request": request}, "id": call_id}])


def manifests(*intents: str):
    return [{"INTENT": intent, "DESCRIPTION": f"处理{intent}"} for intent in intents]


def test_direct_final_uses_no_child_agent():
    model = ScriptedModel(AIMessage(content="你好，我是晓问。"))
    loaded = []

    def load_child(intent):
        loaded.append(intent)

    loop = AgentLoop(model=model, discover_agents=lambda: manifests("其他"), load_child=load_child)

    result = loop.run({"user_input": "你好", "recent": "无"})

    assert result["answer"] == "你好，我是晓问。"
    assert result["intent"] == "其他"
    assert loaded == []


def test_side_effecting_child_receives_original_user_input():
    model = ScriptedModel(call("agent_0", "用户改为明天去广州"), AIMessage(content="完成"))
    seen = {}

    def load_child(_intent):
        def run(state):
            seen.update(state)
            return {"answer": "已规划"}

        return SimpleNamespace(run=run)

    loop = AgentLoop(model=model, discover_agents=lambda: manifests("行程规划"), load_child=load_child)
    loop.run({"user_input": "2026-09-20去北京开会", "recent": "无"})

    assert seen["user_input"] == "2026-09-20去北京开会"
    assert seen["agent_request"] == "用户改为明天去广州"
    assert seen["_defer_writes"] is True


def test_tool_result_is_observed_before_next_decision():
    model = ScriptedModel(call("agent_0", "住宿标准是什么"), AIMessage(content="住宿标准如下。"))
    seen = []

    def load_child(intent):
        assert intent == "知识问答"

        def run(state):
            seen.append(state)
            return {
                "answer": "一线城市住宿标准为 500 元。",
                "policy_status": "grounded",
                "sources": [{"evidence_id": "ev-1", "source": "差旅政策", "text": "500 元"}],
            }

        return SimpleNamespace(run=run)

    loop = AgentLoop(model=model, discover_agents=lambda: manifests("知识问答"), load_child=load_child)
    result = loop.run({"user_input": "住宿标准是什么", "recent": "无", "session_id": "thread", "user_id": "alice"})

    assert seen[0]["user_input"] == "住宿标准是什么"
    assert model.inputs[1][-1].type == "tool"
    assert "500 元" in str(model.inputs[1][-1].content)
    assert result["sources"][0]["evidence_id"] == "ev-1"
    assert result["policy_status"] == "grounded"
    assert [message["role"] for message in result["transcript"]] == ["user", "assistant", "tool", "assistant"]


def test_multiple_child_calls_are_model_driven():
    model = ScriptedModel(
        call("agent_0", "查询住宿政策", "policy"),
        call("agent_1", "查询北京天气", "weather"),
        AIMessage(content="政策和天气都查好了。"),
    )
    calls = []

    def load_child(intent):
        def run(state):
            calls.append((intent, state["agent_request"]))
            if intent == "知识问答":
                return {
                    "answer": "知识问答结果",
                    "policy_status": "grounded",
                    "sources": [{"evidence_id": "ev-1", "source": "政策", "text": "标准"}],
                }
            return {"answer": "联网查询结果", "realtime_status": "grounded"}

        return SimpleNamespace(run=run)

    loop = AgentLoop(model=model, discover_agents=lambda: manifests("知识问答", "联网查询"), load_child=load_child)
    result = loop.run({"user_input": "查住宿政策和北京天气", "recent": "无"})

    assert calls == [("知识问答", "查询住宿政策"), ("联网查询", "查询北京天气")]
    assert result["answer"] == "知识问答结果\n\n联网查询结果"
    assert result["intent"] == "联网查询"


def test_child_failure_is_returned_to_model_for_recovery():
    model = ScriptedModel(call("agent_0", "查天气"), AIMessage(content="实时服务暂不可用，请稍后再试。"))

    def load_child(_intent):
        def run(_state):
            raise RuntimeError("weather down")

        return SimpleNamespace(run=run)

    loop = AgentLoop(model=model, discover_agents=lambda: manifests("联网查询"), load_child=load_child)
    result = loop.run({"user_input": "查天气", "recent": "无"})

    assert "weather down" not in str(model.inputs[1][-1].content)
    assert "子 Agent 执行失败" in str(model.inputs[1][-1].content)
    assert result["answer"] == "暂时无法获取可靠天气信息，请稍后重试。"


def test_repeated_call_is_blocked_and_loop_is_bounded():
    model = ScriptedModel(*[call("agent_0", "同一个请求", f"call-{index}") for index in range(4)])
    executions = []

    def load_child(_intent):
        def run(_state):
            executions.append(1)
            return {"answer": "结果"}

        return SimpleNamespace(run=run)

    loop = AgentLoop(
        model=model,
        discover_agents=lambda: manifests("其他"),
        load_child=load_child,
        limits=LoopLimits(max_steps=4, max_repeat_calls=2),
    )
    result = loop.run({"user_input": "循环", "recent": "无"})

    assert len(executions) == 1
    assert result["failure"]["code"] == "agent_limit"


def test_active_trip_accepts_pure_city_as_missing_destination():
    assert _trip_requested(
        {
            "user_input": "杭州",
            "active_task": {"intent": "行程规划", "missing": ["目的城市"]},
        }
    )


def test_trip_gate_accepts_non_whitelist_origin_city():
    """「从临沂出发」补缺：临沂不在 KNOWN_CITIES 白名单，但仍是有效的出发城市补全"""
    turn = {
        "user_input": "从临沂出发",
        "active_task": {"intent": "行程规划", "missing": ["出发城市"]},
    }
    assert _provides_origin("从临沂出发")
    assert _trip_requested(turn)


def test_trip_gate_new_trip_not_blocked_by_active_task():
    """active_task 存在时，用户换目的地重提新行程，门禁不得拦截（曾致 agent_limit）"""
    active = {"intent": "行程规划", "missing": ["出发城市"]}
    # 新行程（去武汉开会）不是补全北京的「出发城市」，但仍是行程请求
    assert _trip_requested({"user_input": "后天我要去武汉开两天的会", "active_task": active})
    assert _trip_requested({"user_input": "去武汉出差3天", "active_task": active})
    # 纯闲聊/无关话术仍被拒
    assert not _trip_requested({"user_input": "好的", "active_task": active})
    assert not _trip_requested({"user_input": "武汉天气怎么样", "active_task": active})


def test_provides_origin_variants():
    assert _provides_origin("从临沂出发")
    assert _provides_origin("常驻临沂")
    assert _provides_origin("临沂")
    assert _provides_origin("临沂市")
    assert not _provides_origin("好的")
    assert not _provides_origin("算了不去了")


def test_trip_gate_accepts_pure_fact_listing():
    """纯要素列举（无目的词/触发词）也是新行程请求：如「后天, 2人, 去武汉, 2天」"""
    assert _trip_requested({"user_input": "后天, 2人, 去武汉, 2天"})
    assert _trip_requested({"user_input": "去武汉 2天"})
    assert _trip_requested({"user_input": "2人去武汉"})
    assert _trip_requested({"user_input": "后天去武汉"})
    assert _trip_requested({"user_input": "10月8日去北京"})
    # 非行程请求仍被拒：无目的地/无天数/无日期
    assert not _trip_requested({"user_input": "武汉天气怎么样"})
    assert not _trip_requested({"user_input": "报销标准是什么"})
    # 票务执行是商旅平台职责，不是行程规划：不能被「日期+目的地」规则误判
    assert not _trip_requested({"user_input": "帮我订明天去北京的高铁票"})
    assert not _trip_requested({"user_input": "买两张去上海的机票"})
    assert not _trip_requested({"user_input": "查一下明天去广州的余票"})


def test_trip_gate_accepts_modify_existing_trip():
    """修改已有行程（改期/改人数/改细节）在有最近行程时也触发行程规划。"""
    turn = {"user_input": "改成一男一女", "latest_trip": {"id": 1, "status": "upcoming"}}
    assert _trip_requested(turn)
    assert _trip_requested({"user_input": "改期到明天", "latest_trip": {"id": 1}})
    # 无最近行程时，修改词不构成行程请求（无处可改）
    assert not _trip_requested({"user_input": "改成一男一女"})


def test_message_tokens_ignores_cumulative_usage():
    """usage_metadata.total_tokens 是累计值，不得作为增量累加（曾几何虚增触发 token 上限）"""
    msg = AIMessage(
        content="",
        tool_calls=[{"name": "agent_0", "args": {"request": "从临沂出发"}, "id": "c1"}],
        usage_metadata={"total_tokens": 9000, "input_tokens": 8990, "output_tokens": 10},
    )
    assert _message_tokens(msg) < 200  # 按字符估算，而非 9000


def test_needs_info_answer_reuses_child_text_not_supervisor_rambling():
    """行程规划追问缺项时，最终答案直接复用子 Agent 缺项话术，不输出主管思维链"""
    child_text = "⚠️ 还缺一些信息才能帮你安排行程，请补充：\n· 出发城市"
    rambling = (
        "好的，目前没有已记录的常驻城市偏好。我需要向用户询问出发城市。\n\n"
        "根据行程规划的结果，目前缺少出发城市。我需要向用户确认。\n\n---\n\n"
        "您的行程规划还缺少…"
    )
    result = _result(
        "帮我规划10月8日去北京开会4天的行程",
        rambling,
        [
            (
                "行程规划",
                {
                    "answer": child_text,
                    "plan": None,
                    "task_update": {
                        "action": "set",
                        "task": {"intent": "行程规划", "resume_context": "…", "missing": ["出发城市"]},
                    },
                },
            )
        ],
        [],
    )
    assert result["answer"] == child_text
    assert "我需要" not in result["answer"]
    assert "好的，目前" not in result["answer"]


def test_unsolicited_trip_side_effect_is_blocked():
    model = ScriptedModel(
        call("agent_0", "用户说出差不吃辣", "trip"),
        call("agent_1", "记录不吃辣", "preference"),
        AIMessage(content="偏好已记录。"),
    )
    loaded = []

    def load_child(intent):
        loaded.append(intent)
        return SimpleNamespace(run=lambda _state: {"answer": "完成"})

    loop = AgentLoop(
        model=model,
        discover_agents=lambda: manifests("行程规划", "偏好记录"),
        load_child=load_child,
    )
    result = loop.run({"user_input": "我出差不吃辣", "recent": "无", "active_task": None})

    assert loaded == ["偏好记录"]
    assert result["intent"] == "偏好记录"


def test_failed_side_effecting_agent_is_not_retried():
    model = ScriptedModel(
        call("agent_0", "记录两个偏好", "first"),
        call("agent_0", "记录两个偏好", "retry"),
        AIMessage(content="记录失败。"),
    )
    executions = []

    def load_child(_intent):
        def run(_state):
            executions.append(1)
            raise RuntimeError("partial write")

        return SimpleNamespace(run=run)

    loop = AgentLoop(model=model, discover_agents=lambda: manifests("偏好记录"), load_child=load_child)
    loop.run({"user_input": "记录两个偏好", "recent": "无"})

    assert len(executions) == 1


def test_cancellation_stops_before_model_call():
    model = ScriptedModel(AIMessage(content="不应调用"))
    events: list[dict] = []
    loop = AgentLoop(model=model, discover_agents=lambda: manifests("其他"), cancelled=lambda: True)

    result = loop.run({"user_input": "取消", "recent": "无"}, events.append)

    assert model.inputs == []
    assert result["failure"]["code"] == "cancelled"
    assert events[-1]["type"] == "error"


def test_cancellation_after_child_has_matching_tool_result():
    model = ScriptedModel(call("agent_0", "查天气"))
    state = {"cancelled": False}

    def load_child(_intent):
        def run(_turn):
            state["cancelled"] = True
            return {"answer": "天气结果", "realtime_status": "grounded"}

        return SimpleNamespace(run=run)

    loop = AgentLoop(
        model=model,
        discover_agents=lambda: manifests("联网查询"),
        load_child=load_child,
        cancelled=lambda: state["cancelled"],
    )
    result = loop.run({"user_input": "查天气", "recent": "无"})

    assert result["failure"]["code"] == "cancelled"
    assert [message["role"] for message in result["transcript"]] == ["user", "assistant", "tool"]


def test_deadline_is_a_hard_turn_boundary():
    model = ScriptedModel(AIMessage(content="不应调用"))
    loop = AgentLoop(
        model=model,
        discover_agents=lambda: manifests("其他"),
        limits=LoopLimits(timeout_seconds=0),
    )

    started = time.monotonic()
    result = loop.run({"user_input": "超时", "recent": "无"})

    assert time.monotonic() - started < 1
    assert model.inputs == []
    assert result["failure"]["code"] == "agent_timeout"


def test_single_model_response_cannot_exceed_tool_call_budget():
    calls = [{"name": "agent_0", "args": {"request": f"请求{index}"}, "id": f"call-{index}"} for index in range(7)]
    model = ScriptedModel(AIMessage(content="", tool_calls=calls))
    executions = []

    def load_child(_intent):
        def run(_state):
            executions.append(1)
            return {"answer": "完成"}

        return SimpleNamespace(run=run)

    loop = AgentLoop(
        model=model,
        discover_agents=lambda: manifests("其他"),
        load_child=load_child,
        limits=LoopLimits(max_tool_calls=6),
    )

    result = loop.run({"user_input": "批量请求", "recent": "无"})

    assert len(executions) == 6
    assert result["failure"]["code"] == "agent_limit"
    assert result["transcript"][-1]["role"] == "tool"


def test_token_budget_stops_before_model_call():
    model = ScriptedModel(AIMessage(content="不应调用"))
    loop = AgentLoop(
        model=model,
        discover_agents=lambda: manifests("其他"),
        limits=LoopLimits(max_tokens=1),
    )

    result = loop.run({"user_input": "很长的请求", "recent": "无"})

    assert model.inputs == []
    assert result["failure"]["code"] == "agent_token_limit"


def test_policy_claim_without_knowledge_observation_is_rejected():
    model = ScriptedModel(AIMessage(content="公司住宿标准是 999 元。"))
    loop = AgentLoop(model=model, discover_agents=lambda: manifests("知识问答"))

    result = loop.run({"user_input": "公司住宿标准是多少", "recent": "无"})

    assert "999" not in result["answer"]
    assert result["policy_status"] == "not_found"


def test_malformed_child_output_becomes_observable_error():
    model = ScriptedModel(call("agent_0", "查天气"), AIMessage(content="服务失败。"))
    loop = AgentLoop(
        model=model,
        discover_agents=lambda: manifests("联网查询"),
        load_child=lambda _intent: SimpleNamespace(run=lambda _state: {"answer": "晴", "realtime_status": []}),
    )

    result = loop.run({"user_input": "查天气", "recent": "无"})

    assert "子 Agent 执行失败" in str(model.inputs[1][-1].content)
    assert result["answer"] == "暂时无法获取可靠天气信息，请稍后重试。"


def test_ungrounded_policy_answer_is_exact_child_failure_not_supervisor_claim():
    model = ScriptedModel(
        call("agent_0", "住宿标准是什么"),
        AIMessage(content="住宿标准是 999 元。"),
    )
    loop = AgentLoop(
        model=model,
        discover_agents=lambda: manifests("知识问答"),
        load_child=lambda _intent: SimpleNamespace(
            run=lambda _state: {"answer": "未检索到相关政策。", "policy_status": "not_found", "sources": []}
        ),
    )

    result = loop.run({"user_input": "住宿标准是什么", "recent": "无"})

    assert result["answer"] == "未检索到相关政策。"
    assert "999" not in result["answer"]
