import time
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from xiao_wen.agent_loop import AgentLoop, LoopLimits


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
            calls.append((intent, state["user_input"]))
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
    assert result["intent"] == "知识问答"


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


def test_ticket_answer_is_exact_child_result():
    model = ScriptedModel(
        call("agent_0", "查上海到北京高铁票"),
        AIMessage(content="G1 还有票，二等座 553 元。"),
    )
    official = (
        "已生成铁路12306官方预填查询入口：上海 → 北京南，出发日期 2026-08-20\n"
        "https://kyfw.12306.cn/otn/leftTicket/init?fs=上海,SHH&ts=北京南,VNP&date=2026-08-20\n"
        "车站名称和电报码来自12306官方车站数据；请在12306页面确认实际车次、余票、票价和乘车人信息；晓问不代购票。"
    )
    loop = AgentLoop(
        model=model,
        discover_agents=lambda: manifests("联网查询"),
        load_child=lambda _intent: SimpleNamespace(
            run=lambda _state: {"answer": official, "ticket_status": "official"}
        ),
    )

    result = loop.run({"user_input": "查上海到北京高铁票", "recent": "无"})

    assert result["answer"] == official


def test_ticket_gate_rejects_unverified_child_claims():
    model = ScriptedModel(
        call("agent_0", "查上海到北京高铁票"),
        AIMessage(content="G1 还有票，二等座 553 元。"),
    )
    loop = AgentLoop(
        model=model,
        discover_agents=lambda: manifests("联网查询"),
        load_child=lambda _intent: SimpleNamespace(
            run=lambda _state: {"answer": "G1 还有票，二等座 553 元。", "ticket_status": "official"}
        ),
    )

    result = loop.run({"user_input": "查上海到北京高铁票", "recent": "无"})

    assert "G1" not in result["answer"]
    assert "官方链接" in result["answer"]
