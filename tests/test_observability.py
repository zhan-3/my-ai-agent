import asyncio
import json
import stat

from xiao_wen import observability, webapp
from xiao_wen.observability import Recorder


def test_turn_observer_appends_redacted_private_jsonl(monkeypatch, tmp_path):
    trace_file = tmp_path / "private" / "turns.jsonl"
    monkeypatch.setenv("OBSERVABILITY_DEBUG", "true")
    monkeypatch.setenv("OBSERVABILITY_TRACE_FILE", str(trace_file))

    observer = observability.start_turn("住宿标准", "trace-user")
    assert observer is not None
    observer.recorder.record(
        {
            "type": "debug",
            "token": "secret-token",
            "nested": {"api_key": "secret-key", "safe": "visible"},
        }
    )
    observer.finish()
    observer.finish()

    records = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["events"][0] == {"type": "input", "text": "住宿标准", "session_id": "trace-user"}
    assert records[0]["events"][1]["token"] == "<REDACTED>"
    assert records[0]["events"][1]["nested"] == {"api_key": "<REDACTED>", "safe": "visible"}
    assert stat.S_IMODE(trace_file.stat().st_mode) == 0o600


def test_observed_chat_attaches_recorder_and_finishes(monkeypatch):
    class Observer:
        recorder = Recorder()
        finished = False

        def finish(self):
            self.finished = True

    observer = Observer()
    calls = []
    monkeypatch.setattr(observability, "start_turn", lambda text, user: observer)

    def fake_run_chat(text, user, **kwargs):
        calls.append((text, user, kwargs))
        return "result"

    monkeypatch.setattr(webapp, "run_chat", fake_run_chat)

    assert webapp._observed_chat("你好", "trace-user", "trace-user:conversation") == "result"
    assert calls == [
        (
            "你好",
            "trace-user:conversation",
            {"user_id": "trace-user", "recorder": observer.recorder},
        )
    ]
    assert observer.finished


def test_observed_stream_attaches_recorder_and_finishes(monkeypatch):
    class Observer:
        recorder = Recorder()
        finished = False

        def finish(self):
            self.finished = True

    observer = Observer()
    calls = []
    monkeypatch.setattr(observability, "start_turn", lambda text, user: observer)

    async def fake_stream(text, user, **kwargs):
        calls.append((text, user, kwargs))
        yield {"type": "done"}

    monkeypatch.setattr(webapp, "stream_chat", fake_stream)

    async def collect():
        return [event async for event in webapp._observed_stream("你好", "trace-user", "trace-user:conversation")]

    assert asyncio.run(collect()) == [{"type": "done"}]
    assert calls == [
        (
            "你好",
            "trace-user:conversation",
            {"user_id": "trace-user", "recorder": observer.recorder},
        )
    ]
    assert observer.finished


def test_stream_chat_records_loop_events_final_and_memory_write():
    from xiao_wen.session import stream_chat

    recorder = Recorder()

    class Loop:
        def run(self, state, emit=None):
            emit({"type": "run_start"})
            return {"answer": "你好", "intent": "其他", "reason": "问候", "transcript": []}

    async def collect():
        return [event async for event in stream_chat("你好", loop=Loop(), recorder=recorder)]

    events = asyncio.run(collect())
    assert events[-1]["type"] == "done"
    assert [event["type"] for event in recorder.events] == ["recent", "run_start", "final", "memory_write"]
