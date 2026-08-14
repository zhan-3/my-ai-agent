"""eval harness（票 #01）测试：trace 采集 + 结构层校验器 + runner 迁移。

原则：不烧 LLM——graph 层用假 classify/假 agent（monkeypatch 模块属性），
runner 注入假 classify_fn；真实链路验证交给 scripts/eval/run.py 手动跑。
"""

from __future__ import annotations

import json

import pytest

from xiao_wen.eval import metrics, runners, trace

# ---- 假件：不烧 LLM 的最小可运行图 ----


class _FakeStore:
    """假记忆：recent 固定 + 写回记录。"""

    def __init__(self) -> None:
        self.writes: list[tuple[str, str]] = []

    def format_recent_messages(self, n: int, *, session_id: str = "default") -> str:
        return "用户: 你好\n助手: 有什么可以帮你"

    def add_message(self, role: str, content: str, session_id: str = "default") -> None:
        self.writes.append((role, content))


def _fake_classify(recent: str, user_input: str):
    from xiao_wen.intent import IntentResult, SubTask

    return IntentResult(intent="行程规划", reason="测试假件", subtasks=[SubTask(intent="行程规划", text=user_input)])


def _fake_agent_run(state):
    return {"answer": "已为你规划行程", "plan": {"summary": "上海→北京", "days": []}}


@pytest.fixture()
def traced_graph_env(monkeypatch):
    """真图 + 假分类/假 agent：classify 事件与 agent 事件都真实走图内插桩，不碰 LLM。"""
    import types

    import xiao_wen.graph_builder as gb

    monkeypatch.setattr(gb, "intent", types.SimpleNamespace(classify=_fake_classify))
    monkeypatch.setattr(gb, "load_agent", lambda name: types.SimpleNamespace(run=_fake_agent_run))


def test_run_chat_with_trace_records_full_chain(traced_graph_env):
    """整轮 chat 的事件序列：input → recent → classify → agent → final → memory_write。"""
    store = _FakeStore()
    _, events = trace.run_chat_with_trace("去北京开会", session_id="t1", store=store)

    types = [e["type"] for e in events]
    assert types == ["input", "recent", "classify", "agent", "final", "memory_write"]
    # classify 事件：intent 可判定（subtasks 已序列化为字符串列表，不是 SubTask 对象）
    classify_ev = events[2]
    assert classify_ev["intent"] == "行程规划"
    assert classify_ev["subtasks"] == ["行程规划"]
    # agent 事件：只留白名单键（answer/plan），不落大 state
    agent_ev = events[3]
    assert agent_ev["agent"] == "行程规划"
    assert set(agent_ev["out"]) == {"answer", "plan"}
    assert agent_ev["out"]["answer"] == "已为你规划行程"
    # final：契约输出 + 记忆写回（并行 merge 会给 answer 加「⚡ 同时处理」前缀）
    assert events[4]["intent"] == "行程规划"
    assert "已为你规划行程" in events[4]["answer"]
    assert store.writes[0] == ("user", "去北京开会")
    assert store.writes[1][0] == "assistant"
    assert "已为你规划行程" in store.writes[1][1]


def test_recorder_events_are_json_serializable(traced_graph_env):
    """trace 事件必须能落 jsonl：subtasks/plan 等结构转换后全部 JSON 可解析。"""
    _, events = trace.run_chat_with_trace("去北京", session_id="t2", store=_FakeStore())
    for e in events:
        json.dumps(e, ensure_ascii=False)  # 抛异常即失败


def test_recorder_dump_writes_jsonl(tmp_path):
    rec = trace.Recorder()
    rec.record({"type": "input", "text": "hi"})
    rec.record({"type": "classify", "intent": "行程规划"})
    out = tmp_path / "trace.jsonl"
    rec.dump(out)
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert [line["type"] for line in lines] == ["input", "classify"]


# ---- 结构层校验器 ----


def test_check_trip_plan_valid():
    plan = {
        "summary": "上海→北京 4天",
        "days": [
            {"date": "2026-10-08", "transport": "高铁", "hotel": "全季", "activities": ["开会"], "notes": ""},
            {"date": "2026-10-09", "transport": "地铁", "hotel": "全季", "activities": ["拜访"], "notes": ""},
        ],
    }
    assert metrics.check_trip_plan(plan, expected_days=2) == []


def test_check_trip_plan_problems():
    problems = metrics.check_trip_plan(None)
    assert "plan" in problems[0]

    bad = {
        "summary": "",
        "days": [
            {"date": "昨天", "transport": "", "activities": []},  # 日期不可解析 + 缺 hotel/notes 字段
        ],
    }
    problems = metrics.check_trip_plan(bad, expected_days=2)
    joined = "\n".join(problems)
    assert "summary" in joined
    assert "days 数量 1 != 期望 2" in joined
    assert "日期不可解析" in joined
    assert "缺字段" in joined


def test_check_trip_plan_skips_date_when_vague():
    """date_is_vague=True（日期模糊标记）→ 不查日期格式，只查字段齐全。"""
    plan = {
        "summary": "去北京",
        "date_is_vague": True,
        "days": [{"date": "待定", "transport": "", "hotel": "", "activities": [], "notes": ""}],
    }
    assert metrics.check_trip_plan(plan) == []


# ---- runner 迁移（run.py 的 _collect 逻辑迁进 eval 包，注入 classifier 可单测） ----


def test_run_intent_set_with_injected_classifier():
    cases = [
        {"input": "帮我规划去北京的行程", "expected": "行程规划"},
        {"input": "出差住宿标准是什么", "expected": "知识问答"},
    ]
    results, failures = runners.run_intent_set(cases, classify_fn=_fake_classify, verbose=False)
    assert len(results) == 2
    # 假 classifier 恒返回行程规划 → 第一条对、第二条错
    assert [f["id"] for f in failures] == ["intent-001"]
    assert results[0]["got"] == "行程规划"
    assert results[1]["got"] == "行程规划"
