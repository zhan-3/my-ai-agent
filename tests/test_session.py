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
    # 注入的 recent 包含历史
    assert "上一轮" in graph.calls[0]["recent"]
    assert graph.calls[0]["user_input"] == "新问题"
    # 写回两轮
    msgs = memory_store.load_memory()["messages"]
    assert [m["role"] for m in msgs[-2:]] == ["user", "assistant"]
    assert [m["content"] for m in msgs[-2:]] == ["新问题", "答"]


def test_chat_propagates_exceptions():
    class BoomGraph:
        def invoke(self, state):
            raise RuntimeError("LLM 挂了")

    with pytest.raises(RuntimeError, match="LLM 挂了"):
        chat("x", graph=BoomGraph())


def test_chat_uses_injected_store():
    calls = []

    class FakeStore:
        def format_recent_messages(self, n):
            return "无历史"

        def add_message(self, role, content):
            calls.append((role, content))

    graph = FakeGraph()
    r = chat("hi", graph=graph, store=FakeStore())
    assert r.answer == "答"
    assert calls == [("user", "hi"), ("assistant", "答")]
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
