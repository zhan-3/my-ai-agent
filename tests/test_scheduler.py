"""调度优化（并行路径）测试：dispatch fan-out / make_parallel 包装 / merge fan-in

并行组件随建图代码收口于图工厂（graph_builder，深模块）——测试直接测组件纯逻辑，
无需 LLM：用桩 worker + 迷你图复刻组装，断言 Send 拆分与合并汇总。
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.types import Send

from xiao_wen import graph_builder as gb
from xiao_wen.intent import SubTask

# ---------------- 纯逻辑件 ----------------


def test_dispatch_sends_fanout_for_subtasks():
    state = {
        "subtasks": [SubTask(intent="知识问答", text="a"), SubTask(intent="联网查询", text="b")],
        "intent": "知识问答",
        "recent": "上文…",
        "session_id": "会话X",
        "messages": ["m1"],
    }
    out = gb.dispatch(state)
    assert isinstance(out, list) and len(out) == 2
    assert all(isinstance(s, Send) for s in out)
    assert [s.node for s in out] == ["p_知识问答", "p_联网查询"]
    # 并行分支必须继承上文（recent/session_id/messages）：
    # 否则补全轮的子 Agent 看不到上轮要素（续接失效的根因，实测踩过）
    for s in out:
        assert s.arg["recent"] == "上文…"
        assert s.arg["session_id"] == "会话X"
        assert s.arg["messages"] == ["m1"]
        assert s.arg["current_task"].text in ("a", "b")


def test_dispatch_string_route_when_single():
    state = {"subtasks": [], "intent": "历史查询"}
    assert gb.dispatch(state) == "历史查询"


def test_dispatch_prepends_primary_when_omitted_from_subtasks():
    """LLM 漏掉主导意图时，用完整输入补一条主导意图分支（防行程规划被静默丢弃）"""
    state = {
        "subtasks": [SubTask(intent="偏好记录", text="喜欢住连锁酒店")],
        "intent": "行程规划",
        "user_input": "我下周从北京去杭州出差三天，喜欢住连锁酒店，帮我安排一下行程。",
    }
    out = gb.dispatch(state)
    assert isinstance(out, list) and len(out) == 2
    assert [s.node for s in out] == ["p_行程规划", "p_偏好记录"]
    primary = out[0]
    assert primary.arg["current_task"].intent == "行程规划"
    assert primary.arg["current_task"].text == state["user_input"]


def test_make_parallel_routes_current_task():
    seen = []

    def worker(state):
        seen.append(state["user_input"])
        return {"answer": "已处理"}

    node = gb.make_parallel(worker)
    out = node({"current_task": SubTask(intent="历史查询", text="查上次行程"), "user_input": "原输入"})
    assert out["collected"] == [
        {
            "intent": "历史查询",
            "text": "查上次行程",
            "answer": "已处理",
            "plan": None,
            "stats": None,
            "history": None,
        }
    ]
    assert seen == ["查上次行程"]


def test_merge_summarizes_all_parts():
    out = gb.merge(
        {
            "collected": [
                {"intent": "知识问答", "text": "住宿标准", "answer": "答A"},
                {"intent": "联网查询", "text": "天气", "answer": "答B"},
            ]
        }
    )
    assert "2 个请求" in out["answer"]
    assert "答A" in out["answer"] and "答B" in out["answer"]


def test_merge_sources_empty_when_branches_have_none():
    out = gb.merge({"collected": [{"intent": "联网查询", "text": "天气", "answer": "晴"}]})
    assert out["sources"] == []


def test_merge_sources_preserves_single_branch_order():
    sources = [
        {"evidence_id": "ev-1", "source": "政策A", "text": "片段A"},
        {"evidence_id": "ev-2", "source": "政策B", "text": "片段B"},
    ]
    out = gb.merge({"collected": [{"intent": "知识问答", "text": "标准", "answer": "答", "sources": sources}]})
    assert out["sources"] == sources


def test_merge_sources_deduplicates_by_evidence_id_in_branch_order():
    first = {"evidence_id": "ev-1", "source": "政策A", "text": "首个版本"}
    duplicate = {"evidence_id": "ev-1", "source": "政策A", "text": "重复版本"}
    second = {"evidence_id": "ev-2", "source": "政策B", "text": "片段B"}
    out = gb.merge(
        {
            "collected": [
                {"intent": "知识问答", "text": "标准", "answer": "答A", "sources": [first]},
                {"intent": "联网查询", "text": "天气", "answer": "答B", "sources": [duplicate, second]},
            ]
        }
    )
    assert out["sources"] == [first, second]


# ---------------- 迷你图：fan-out → fan-in 端到端（无 LLM） ----------------


class MiniState(TypedDict):
    messages: Annotated[list, add_messages]
    user_input: str
    recent: str
    intent: str
    reason: str
    answer: str
    subtasks: list[dict]
    current_task: dict
    collected: Annotated[list[dict], operator.add]


def _build_mini_graph():
    def fake_worker(state):
        return {"answer": f"答[{state['user_input'][:4]}]"}

    workers = {"知识问答": fake_worker, "联网查询": fake_worker}

    def classify_intent(state):
        return {
            "intent": "知识问答",
            "reason": "多意图",
            "subtasks": [SubTask(intent="知识问答", text="政策问题"), SubTask(intent="联网查询", text="天气问题")],
        }

    g = StateGraph(MiniState)
    g.add_node(classify_intent)
    for name, fn in workers.items():
        g.add_node(name, fn)
        g.add_node(f"p_{name}", gb.make_parallel(fn))
    g.add_node(gb.merge)
    g.add_edge(START, "classify_intent")
    g.add_conditional_edges("classify_intent", gb.dispatch, {n: n for n in workers})
    for name in workers:
        g.add_edge(f"p_{name}", "merge")
    g.add_edge("merge", END)
    for name in workers:
        g.add_edge(name, END)
    return g.compile()


def test_mini_graph_fanout_merge():
    app = _build_mini_graph()
    out = app.invoke({"user_input": "x", "recent": "", "messages": []})
    assert "2 个请求" in out["answer"]
    assert "政策问题" in out["answer"] and "天气问题" in out["answer"]
    assert "答[政策问题]" in out["answer"] and "答[天气问题]" in out["answer"]


def test_product_graph_preserves_sources_across_knowledge_and_web_branches(monkeypatch):
    import types

    from xiao_wen.intent import IntentResult

    source = {"evidence_id": "ev-policy", "source": "差旅政策", "text": "住宿标准 500 元"}

    def fake_classify(recent, user_input):
        return IntentResult(
            intent="知识问答",
            reason="政策与天气",
            subtasks=[
                SubTask(intent="知识问答", text="住宿标准是多少"),
                SubTask(intent="联网查询", text="北京天气如何"),
            ],
        )

    def fake_load_agent(name):
        def run(state):
            if name == "知识问答":
                return {"answer": "住宿标准 500 元", "sources": [source]}
            return {"answer": "北京晴"}

        return types.SimpleNamespace(run=run)

    monkeypatch.setattr(gb.intent, "classify", fake_classify)
    monkeypatch.setattr(gb, "load_agent", fake_load_agent)
    app = gb.build_supervisor_graph(recorder=types.SimpleNamespace(record=lambda event: None))

    out = app.invoke({"user_input": "住宿标准是多少，并查北京天气", "recent": "", "messages": []})

    assert out["sources"] == [source]
