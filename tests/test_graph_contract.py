"""图级契约测试：真实图拓扑 + 假 LLM（只注入 LLM / RAG 检索 / 天气三个外部接缝）

与 test_graph_builder.py 的区别：那里 monkeypatch 图的节点（classify / load_agent）；
这里图、classify、子 Agent、trip_planner 编排逻辑全真，只替换外部接缝，证明
「classify → 路由 → collect → 子 agent → 结构化产出 → 记忆写回」的完整数据流。

价值：比逐节点 monkeypatch 的单元测试更接近真实链路（图拓扑、节点数据流、归约器、
collect-then-compose 黑板都真实跑），比 integration（真 LLM）更快、可重复、无需 .env 密钥。
"""

import types
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from xiao_wen import graph_builder as gb
from xiao_wen import intent as intent_mod
from xiao_wen import llm as llm_mod
from xiao_wen import rag as rag_mod
from xiao_wen import trip_planner
from xiao_wen import web as web_mod
from xiao_wen.agents import preference_agent
from xiao_wen.intent import Intent, SubTask
from xiao_wen.memory import get_itineraries, get_preferences


def _prompt_text(input: Any) -> str:
    """把 prompt | runnable 链传给模型的输入（ChatPromptValue 等）转成可断言文本"""
    if isinstance(input, str):
        return input
    to_string = getattr(input, "to_string", None)
    if callable(to_string):
        return to_string()
    to_messages = getattr(input, "to_messages", None)
    if callable(to_messages):
        return "\n".join(str(getattr(m, "content", m)) for m in to_messages())
    return str(input)


class FakeLLM:
    """按结构化输出 Schema 分发工厂的假模型（只注入 llm.get_llm 单一接缝）。

    with_structured_output(Schema) → invoke(text) -> Schema 实例 的 runnable；
    非结构化 invoke → AIMessage(text_factory(text))。
    所有调用记入 self.calls（(schema 名, 格式化 prompt 文本)）供断言。
    """

    def __init__(
        self,
        structured: dict[type, Callable[[str], Any]] | None = None,
        text: Callable[[str], str] | None = None,
    ) -> None:
        self._structured = structured or {}
        self._text = text or (lambda _: "（知识问答占位回答）")
        self.calls: list[tuple[str, str]] = []

    def with_structured_output(self, schema: type, method: str | None = None, **kwargs: Any) -> RunnableLambda:
        outer = self

        def _invoke(input: Any, config: Any = None, **kw: Any) -> Any:
            text = _prompt_text(input)
            outer.calls.append((getattr(schema, "__name__", repr(schema)), text))
            factory = outer._structured.get(schema)
            if factory is None:
                raise AssertionError(f"未注册结构化输出工厂：{getattr(schema, '__name__', schema)}")
            return factory(text)

        return RunnableLambda(_invoke)

    def __call__(self, input: Any, config: Any = None, **kw: Any) -> AIMessage:
        return self.invoke(input, config=config, **kw)

    def invoke(self, input: Any, config: Any = None, **kw: Any) -> AIMessage:
        text = _prompt_text(input)
        self.calls.append(("text", text))
        return AIMessage(content=self._text(text))


def _patch_llm_seam(monkeypatch, fake: FakeLLM) -> None:
    """注入假 LLM 并清空各模块模型缓存（否则 lru_cache 复用真模型 / 旧 fake）"""
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kw: fake)
    intent_mod._intent_model.cache_clear()
    trip_planner._extract_model.cache_clear()
    trip_planner._plan_model.cache_clear()
    preference_agent._pref_model.cache_clear()
    rag_mod._knowledge_model.cache_clear()


def _trip_extract(text: str) -> trip_planner.TripRequest:
    return trip_planner.TripRequest(
        from_city="上海",
        to_city="北京",
        start_date="2026-03-05",
        duration_days=3,
        people_count=1,
        purpose="开会",
        hotel_pref="无",
        budget_pref="中等",
        date_is_vague=False,
    )


def _trip_plan(text: str) -> trip_planner.ItineraryPlan:
    return trip_planner.ItineraryPlan(
        days=[
            trip_planner.DayPlan(
                date=day_date,
                transport="高铁 G1 次 上海虹桥→北京南",
                hotel="全季酒店（北京）",
                activities=["14:00 公务：开会"],
                notes="",
            )
            for day_date in ("2026-03-05", "2026-03-06", "2026-03-07")
        ],
        summary="3 天北京出差行程",
        reasons=["住宿按差旅政策一线城市不超过 500 元/晚"],
    )


def test_trip_planning_end_to_end_contract(monkeypatch):
    """行程规划单意图全链路：classify → collect → 行程 agent → 结构化 plan → 写回记忆

    图与 agent 逻辑全真；只注入 LLM（schema 分发）/ RAG 检索 / 天气三个外部接缝。
    """
    fake = FakeLLM(
        structured={
            Intent: lambda text: Intent(intent="行程规划", reason="规划出差", subtasks=[]),
            trip_planner.TripRequest: _trip_extract,
            trip_planner.ItineraryPlan: _trip_plan,
            preference_agent.PreferenceList: lambda text: preference_agent.PreferenceList(records=[]),
        }
    )
    _patch_llm_seam(monkeypatch, fake)
    monkeypatch.setattr(rag_mod, "load_chunks", lambda: [("policy", "一线城市住宿不超过 500 元/晚")])
    monkeypatch.setattr(rag_mod, "build_index", lambda chunks: object())
    monkeypatch.setattr(
        rag_mod,
        "_search_with_metadata",
        lambda q, col, k=5: [(0.9, {"source": "policy"}, "一线城市住宿不超过 500 元/晚")],
    )
    monkeypatch.setattr(web_mod, "get_weather", types.SimpleNamespace(invoke=lambda d: "北京 晴"))

    app = gb.build_supervisor_graph()
    out = app.invoke({"user_input": "3 月 5 日从上海去北京开会 3 天", "recent": "", "messages": [], "session_id": "s1"})

    # 结构化 plan 流经图到最终 state（含 date_is_vague 展示标记）
    assert out["plan"] is not None
    assert out["plan"]["summary"] == "3 天北京出差行程"
    assert out["plan"]["date_is_vague"] is False
    # answer 含展示三件套：行程格式 / 预算块 / 目的地天气
    assert "3 天北京出差行程" in out["answer"]
    assert "费用估算" in out["answer"]
    assert "目的地天气提醒" in out["answer"]
    # collect 上游政策注入生成（plan 工厂收到的 prompt 含政策原文）
    plan_text = next(t for n, t in fake.calls if n == "ItineraryPlan")
    assert "一线城市住宿不超过 500 元/晚" in plan_text
    # 真实 classify 走了假 LLM 的 Intent schema（非 monkeypatch classify）
    assert any(n == "Intent" for n, _ in fake.calls)
    # 写回长期记忆
    its = get_itineraries(session_id="s1")
    assert len(its) == 1
    assert its[0]["to_city"] == "北京"
    assert its[0]["summary"] == "3 天北京出差行程"


def test_multi_intent_fanout_merge_contract(monkeypatch):
    """多意图并行链路：Send fan-out → 行程分支 + 偏好分支 → merge fan-in

    同时验证竞态修复（collect 串行提取本轮偏好注入行程分支生成）与偏好单一写入者。
    """
    fake = FakeLLM(
        structured={
            Intent: lambda text: Intent(
                intent="行程规划",
                reason="规划 + 记偏好",
                subtasks=[SubTask(intent="偏好记录", text="记一下我喜欢住全季")],
            ),
            trip_planner.TripRequest: _trip_extract,
            trip_planner.ItineraryPlan: _trip_plan,
            preference_agent.PreferenceList: lambda text: (
                preference_agent.PreferenceList(
                    records=[preference_agent.PreferenceRecord(category="住宿", content="喜欢住全季", is_update=False)]
                )
                if "喜欢住全季" in text
                else preference_agent.PreferenceList(records=[])
            ),
        }
    )
    _patch_llm_seam(monkeypatch, fake)
    monkeypatch.setattr(rag_mod, "load_chunks", lambda: [("policy", "一线城市住宿不超过 500 元/晚")])
    monkeypatch.setattr(rag_mod, "build_index", lambda chunks: object())
    monkeypatch.setattr(
        rag_mod,
        "_search_with_metadata",
        lambda q, col, k=5: [(0.9, {"source": "policy"}, "一线城市住宿不超过 500 元/晚")],
    )
    monkeypatch.setattr(web_mod, "get_weather", types.SimpleNamespace(invoke=lambda d: "北京 晴"))

    app = gb.build_supervisor_graph()
    out = app.invoke(
        {
            "user_input": "帮我规划 3 月 5 日去北京开会 3 天，顺便记一下我喜欢住全季",
            "recent": "",
            "messages": [],
            "session_id": "s2",
        }
    )

    # merge fan-in：两个并行分支汇总
    assert "同时为你处理了 2 个请求" in out["answer"]
    assert out["plan"] is not None
    assert out["plan"]["summary"] == "3 天北京出差行程"
    # 偏好分支写库（单一写入者：collect 只提取不写库）
    prefs = get_preferences(session_id="s2")
    assert any(p["category"] == "住宿" and p["content"] == "喜欢住全季" for p in prefs)
    # 竞态修复：collect 串行提取的本轮偏好注入行程分支生成（prompt 含「本轮陈述偏好」）
    plan_text = next(t for n, t in fake.calls if n == "ItineraryPlan")
    assert "本轮陈述偏好：住宿:喜欢住全季" in plan_text
