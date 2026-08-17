"""本地显式观察模式：把一轮结构化 trace 追加到权限受限的 JSONL 文件。"""

from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xiao_wen import ROOT
from xiao_wen.config import load_settings

# 子 Agent 出参白名单：State 大对象不落盘，只记录可回放的稳定结果。
AGENT_OUT_KEYS = ("answer", "plan", "stats", "history", "sources", "policy_status", "failure")
_SENSITIVE_KEYS = {"authorization", "token", "password", "api_key", "apikey", "jwt_secret"}


@dataclass
class Recorder:
    events: list[dict] = field(default_factory=list)

    def record(self, event: dict[str, Any]) -> None:
        self.events.append(event)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "<REDACTED>" if key.lower() in _SENSITIVE_KEYS else _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


@dataclass
class TurnObserver:
    recorder: Recorder
    path: Path
    _finished: bool = False

    def finish(self) -> None:
        """整轮事件作为单行原子追加；重复调用不重复写入。"""
        if self._finished:
            return
        self._finished = True
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = {
            "trace_version": 1,
            "recorded_at": datetime.now(UTC).isoformat(),
            "events": _redact(self.recorder.events),
        }
        descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as trace_file:
            fcntl.flock(trace_file.fileno(), fcntl.LOCK_EX)
            trace_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
            trace_file.flush()
            fcntl.flock(trace_file.fileno(), fcntl.LOCK_UN)
        os.chmod(self.path, 0o600)


def start_turn(text: str, session_id: str) -> TurnObserver | None:
    """配置启用时创建本轮观察器；默认返回 None，生产路径零额外落盘。"""
    settings = load_settings()
    if not settings.observability_debug:
        return None
    path = Path(settings.observability_trace_file)
    if not path.is_absolute():
        path = ROOT / path
    recorder = Recorder()
    recorder.record({"type": "input", "text": text, "session_id": session_id})
    return TurnObserver(recorder=recorder, path=path)
