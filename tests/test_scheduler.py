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
    }
    out = gb.dispatch(state)
    assert isinstance(out, list) and len(out) == 2
    assert all(isinstance(s, Send) for s in out)
    assert [s.node for s in out] == ["p_知识问答", "p_联网查询"]
    assert [s.arg for s in out] == [{"current_task": st} for st in state["subtasks"]]


def test_dispatch_string_route_when_single():
    state = {"subtasks": [], "intent": "历史查询"}
    assert gb.dispatch(state) == "历史查询"


def test_make_parallel_routes_current_task():
    seen = []

    def worker(state):
        seen.append(state["user_input"])
        return {"answer": "已处理"}

    node = gb.make_parallel(worker)
    out = node({"current_task": SubTask(intent="历史查询", text="查上次行程"), "user_input": "原输入"})
    assert out["collected"] == [{"intent": "历史查询", "text": "查上次行程", "answer": "已处理"}]
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
