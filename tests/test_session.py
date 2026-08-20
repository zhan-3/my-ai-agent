"""会话接口测试：Agent Loop、线程锁、事件流和持久化闭环。"""

import asyncio
import threading
import time
from collections.abc import AsyncGenerator
from typing import cast

import pytest

from xiao_wen.session import ChatResult, chat, stream_chat


class Store:
    def __init__(self):
        self.messages: dict[str, list[tuple[str, str]]] = {}
        self.transcripts: dict[str, list[list[dict]]] = {}
        self.preferences = []
        self.itineraries = []
        self.trips = []
        self.task = None

    def format_recent_messages(self, n, *, session_id="default"):
        items = self.messages.get(session_id, [])[-n:]
        return "\n".join(content for _, content in items) or "无"

    def add_message(self, role, content, *, session_id="default", sources=None):
        self.messages.setdefault(session_id, []).append((role, content))

    def add_agent_transcript(self, transcript, *, session_id="default"):
        self.transcripts.setdefault(session_id, []).append(transcript)

    def add_or_update_preference(self, category, content, is_update=False, *, session_id="default"):
        self.preferences.append((session_id, category, content, is_update))

    def add_itinerary(self, facts, summary, *, session_id="default"):
        self.itineraries.append((session_id, facts, summary))

    def save_trip(
        self,
        facts,
        plan,
        *,
        session_id="default",
        thread_id=None,
        trip_id=None,
        status="upcoming",
        missing=None,
        resume_context="",
    ):
        self.trips.append((session_id, facts, plan, trip_id, status))
        return {"id": trip_id or len(self.trips), **facts, "summary": (plan or {}).get("summary", ""), "status": status}

    def get_active_task(self, *, thread_id, user_id):
        return self.task

    def set_active_task(self, task, *, thread_id, user_id):
        self.task = task

    def clear_active_task(self, *, thread_id, user_id):
        self.task = None

    def cancel_active_task(self, *, thread_id, user_id):
        self.task = None


class Loop:
    def __init__(self, result=None, *, fail=None, events=None):
        self.result = result or {"answer": "答", "intent": "其他", "reason": "测试", "transcript": []}
        self.fail = fail
        self.events = events or []
        self.calls = []

    def run(self, turn, emit=None):
        self.calls.append(turn)
        if self.fail:
            raise self.fail
        for event in self.events:
            if emit:
                emit(event)
        return dict(self.result)


def collect_stream(*args, **kwargs):
    async def collect():
        return [event async for event in stream_chat(*args, **kwargs)]

    return asyncio.run(collect())


def test_chat_reads_recent_runs_loop_and_persists_turn_and_transcript():
    store = Store()
    store.add_message("user", "上一轮", session_id="thread")
    transcript = [{"role": "user", "content": "新问题"}, {"role": "assistant", "content": "答"}]
    loop = Loop({"answer": "答", "intent": "其他", "reason": "测试", "transcript": transcript})

    result = chat("新问题", "thread", user_id="alice", loop=loop, store=store)

    assert isinstance(result, ChatResult)
    assert "上一轮" in loop.calls[0]["recent"]
    assert loop.calls[0]["session_id"] == "thread"
    assert loop.calls[0]["user_id"] == "alice"
    assert store.messages["thread"][-2:] == [("user", "新问题"), ("assistant", "答")]
    assert store.transcripts["thread"] == [transcript]


def test_chat_applies_deferred_domain_writes_only_on_success():
    store = Store()
    result = chat(
        "我常住上海",
        "thread",
        user_id="alice",
        loop=Loop(
            {
                "answer": "已记录",
                "intent": "偏好记录",
                "reason": "完成",
                "memory_writes": [{"type": "preference", "category": "常驻城市", "content": "上海", "is_update": True}],
                "transcript": [],
            }
        ),
        store=store,
    )
    assert result.failure is None
    assert store.preferences == [("alice", "常驻城市", "上海", True)]


def test_postgres_turn_rolls_back_all_writes_on_commit_failure():
    from xiao_wen import memory as memory_store

    loop = Loop(
        {
            "answer": "完成",
            "intent": "偏好记录",
            "reason": "完成",
            "memory_writes": [
                {"type": "preference", "category": "住宿", "content": "安静", "is_update": False},
                {"type": "unknown"},
            ],
            "transcript": [{"role": "assistant", "content": "完成"}],
        }
    )

    with pytest.raises(ValueError, match="未知延迟记忆写入"):
        chat("记住偏好", "atomic", user_id="alice", loop=loop, store=memory_store)

    assert memory_store.get_preferences(session_id="alice") == []
    assert memory_store.get_recent_messages(session_id="atomic") == []
    assert memory_store.get_recent_agent_transcripts(session_id="atomic") == []


def test_chat_propagates_structured_outputs_and_sources():
    plan = {
        "summary": "北京出差",
        "reasons": [],
        "days": [],
        "date_is_vague": False,
    }
    source = {"evidence_id": "ev-1", "source": "差旅政策", "text": "标准"}
    result = chat(
        "规划",
        loop=Loop(
            {
                "answer": "行程如下",
                "intent": "行程规划",
                "reason": "观察完成",
                "plan": plan,
                "sources": [source],
                "policy_status": "grounded",
                "transcript": [],
            }
        ),
        store=Store(),
    )

    assert result.plan is not None and result.plan.model_dump() == plan
    assert result.sources[0].evidence_id == "ev-1"
    assert result.policy_status == "grounded"


def test_chat_degrades_malformed_plan_and_empty_answer():
    result = chat(
        "规划",
        loop=Loop({"answer": "", "intent": "行程规划", "reason": "测试", "plan": {"summary": "坏"}}),
        store=Store(),
    )
    assert result.answer == "（暂无回复，请换个说法再试一次）"
    assert result.plan is None


def test_chat_propagates_loop_exception_without_writeback():
    store = Store()
    with pytest.raises(RuntimeError, match="LLM 挂了"):
        chat("问题", loop=Loop(fail=RuntimeError("LLM 挂了")), store=store)
    assert store.messages == {}
    assert store.transcripts == {}


def test_chat_failure_is_not_committed():
    store = Store()
    result = chat(
        "住宿标准",
        loop=Loop(
            {
                "answer": "政策不可用",
                "intent": "知识问答",
                "reason": "依赖失败",
                "failure": {"code": "policy_unavailable", "message": "政策不可用", "retryable": True},
                "transcript": [],
            }
        ),
        store=store,
    )
    assert result.failure is not None
    assert store.messages == {}
    assert store.transcripts == {}


@pytest.mark.parametrize("task_update", [{"action": "set", "task": {"intent": "行程规划"}}, {"action": "clear"}])
def test_failed_turn_never_mutates_active_task(task_update):
    store = Store()
    original = {"intent": "行程规划", "missing": ["出差天数"]}
    store.task = original
    result = chat(
        "问题",
        "thread",
        user_id="alice",
        loop=Loop(
            {
                "answer": "服务失败",
                "intent": "知识问答",
                "reason": "失败",
                "task_update": task_update,
                "failure": {"code": "policy_unavailable", "message": "服务失败", "retryable": True},
            }
        ),
        store=store,
    )
    assert result.failure is not None
    assert store.task == original


def test_active_task_survives_interrupt_and_can_clear():
    store = Store()
    first = Loop(
        {
            "answer": "请补充出发城市",
            "intent": "行程规划",
            "reason": "缺项",
            "task_update": {
                "action": "set",
                "task": {"intent": "行程规划", "missing": ["出发城市"], "resume_context": "用户: 规划"},
            },
        }
    )
    chat("规划", "thread", user_id="alice", loop=first, store=store)
    assert store.task is not None

    interrupted = chat(
        "不吃辣",
        "thread",
        user_id="alice",
        loop=Loop({"answer": "已记录", "intent": "偏好记录", "reason": "偏好"}),
        store=store,
    )
    assert "刚才的行程仍保留" in interrupted.answer
    assert store.task is not None

    chat(
        "上海",
        "thread",
        user_id="alice",
        loop=Loop(
            {
                "answer": "行程完成",
                "intent": "行程规划",
                "reason": "续接",
                "task_update": {"action": "clear"},
            }
        ),
        store=store,
    )
    assert store.task is None


def test_stream_forwards_agent_lifecycle_then_done():
    store = Store()
    events = [
        {"type": "run_start"},
        {"type": "agent_start", "agent": "知识问答", "request": "住宿标准"},
        {"type": "agent_result", "agent": "知识问答", "result": {"answer": "标准"}},
    ]
    out = collect_stream(
        "住宿标准",
        loop=Loop(
            {"answer": "标准", "intent": "知识问答", "reason": "观察完成", "transcript": []},
            events=events,
        ),
        store=store,
    )

    assert out[:3] == [
        {"type": "stage", "status": "start"},
        {"type": "stage", "status": "working", "intent": "知识问答"},
        {"type": "stage", "status": "done", "intent": "知识问答"},
    ]
    assert out[-1]["type"] == "done" and out[-1]["answer"] == "标准"
    assert store.messages["default"] == [("user", "住宿标准"), ("assistant", "标准")]


def test_stream_failure_has_stable_error_and_no_commit():
    store = Store()
    out = collect_stream(
        "住宿标准",
        loop=Loop(
            {
                "answer": "政策不可用",
                "intent": "知识问答",
                "reason": "失败",
                "failure": {"code": "policy_unavailable", "message": "政策不可用", "retryable": True},
                "transcript": [],
            },
            events=[{"type": "run_start"}],
        ),
        store=store,
    )
    assert out[-1] == {
        "type": "error",
        "code": "policy_unavailable",
        "message": "政策不可用",
        "retryable": True,
        "policy_status": "unavailable",
    }
    assert store.messages == {}


def test_stream_exception_becomes_error_event():
    out = collect_stream("问题", loop=Loop(fail=RuntimeError("boom")), store=Store())
    assert out[-1]["type"] == "error"
    assert out[-1]["code"] == "service_unavailable"


def test_default_runtime_is_agent_loop(monkeypatch):
    from xiao_wen import session

    seen = {}

    class DefaultLoop(Loop):
        def __init__(self, **kwargs):
            seen.update(kwargs)
            super().__init__()

    monkeypatch.setattr(session, "AgentLoop", DefaultLoop)
    result = chat("你好", store=Store())
    assert result.answer == "答"
    assert "cancelled" in seen


def test_session_coordinator_reclaims_completed_session():
    from xiao_wen import session

    with session._session_coordinator.turn("reclaim"):
        assert session._session_coordinator.active_session_count == 1
    assert session._session_coordinator.active_session_count == 0


def test_same_session_chat_is_serialized():
    from xiao_wen import session

    sequence = []
    entered = threading.Event()
    release = threading.Event()

    class BlockingLoop(Loop):
        def run(self, turn, emit=None):
            sequence.append(f"{turn['user_input']}:run")
            entered.set()
            release.wait(timeout=3)
            return {"answer": f"{turn['user_input']}-答", "intent": "其他", "reason": "测试"}

    class RecordingStore(Store):
        def add_message(self, role, content, *, session_id="default", sources=None):
            sequence.append(f"{content}:{role}")
            super().add_message(role, content, session_id=session_id, sources=sources)

    store = RecordingStore()

    def run(text):
        session.chat(text, "same", loop=BlockingLoop(), store=store)

    first = threading.Thread(target=run, args=("first",))
    second = threading.Thread(target=run, args=("second",))
    first.start()
    assert entered.wait(timeout=1)
    second.start()
    time.sleep(0.1)
    assert "second:run" not in sequence
    release.set()
    first.join(timeout=3)
    second.join(timeout=3)
    assert sequence == [
        "first:run",
        "first:user",
        "first-答:assistant",
        "second:run",
        "second:user",
        "second-答:assistant",
    ]


def test_different_sessions_stream_in_parallel():
    from xiao_wen import session

    entered = 0
    guard = threading.Lock()
    both = threading.Event()
    release = threading.Event()

    class ParallelLoop(Loop):
        def run(self, turn, emit=None):
            nonlocal entered
            with guard:
                entered += 1
                if entered == 2:
                    both.set()
            release.wait(timeout=2)
            return {"answer": "完成", "intent": "其他", "reason": "测试"}

    async def exercise():
        async def consume(session_id):
            return [event async for event in session.stream_chat("x", session_id, loop=ParallelLoop(), store=Store())]

        tasks = [asyncio.create_task(consume("a")), asyncio.create_task(consume("b"))]
        assert await asyncio.to_thread(both.wait, 1)
        release.set()
        await asyncio.gather(*tasks)

    asyncio.run(exercise())


def test_cancelled_stream_stops_loop_and_skips_commit(monkeypatch):
    from contextlib import suppress

    from xiao_wen import session

    entered = threading.Event()
    store = Store()

    class CancellableLoop:
        def __init__(self, *, cancelled):
            self.cancelled = cancelled

        def run(self, turn, emit=None):
            if emit:
                emit({"type": "run_start"})
            entered.set()
            while not self.cancelled():
                time.sleep(0.01)
            return {
                "answer": "请求已取消",
                "intent": "",
                "reason": "cancelled",
                "failure": {"code": "cancelled", "message": "请求已取消", "retryable": False},
                "transcript": [],
            }

    monkeypatch.setattr(session, "AgentLoop", CancellableLoop)

    async def exercise():
        stream = cast(AsyncGenerator[dict, None], session.stream_chat("x", "cancelled", store=store))
        first = await asyncio.wait_for(anext(stream), 1)
        assert entered.is_set()
        assert first["status"] == "start"
        close = asyncio.ensure_future(stream.aclose())
        with suppress(asyncio.CancelledError):
            await asyncio.wait_for(close, 1)

    asyncio.run(exercise())
    assert store.messages == {}
    assert store.transcripts == {}
    assert session._session_coordinator.active_session_count == 0


def test_many_sessions_do_not_leak_coordinator_entries():
    from xiao_wen import session

    for index in range(100):
        session.chat("x", f"one-{index}", loop=Loop(), store=Store())
    assert session._session_coordinator.active_session_count == 0
