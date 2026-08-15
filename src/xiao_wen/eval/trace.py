"""trace 采集（票 #01）：Recorder + 事件约定 + run_chat_with_trace 包装。

事件行（jsonl 一行一个，全部 JSON 可序列化）：
  input:        {text, session_id}
  recent:       {recent}                          （session.chat 插桩）
  classify:     {intent, reason, subtasks[]}      （graph classify_intent 节点插桩）
  agent:        {agent, out{白名单键}}            （graph 每个 agent 节点插桩）
  final:        {intent, reason, answer, plan, stats, history}
  memory_write: {user, assistant}

采集链路：run_chat_with_trace 构造带 Recorder 的图（绕过指纹缓存）交给 session.chat，
chat 内部三处插桩（recent/final/memory_write），graph 内两处插桩（classify/agent）。
生产路径零改动：所有插桩点都有 `recorder is not None` 守卫，默认 None 行为不变。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# agent 出参白名单：state 大对象不落盘，只留可判定的键
AGENT_OUT_KEYS = ("answer", "plan", "stats", "history")


@dataclass
class Recorder:
    events: list[dict] = field(default_factory=list)

    def record(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def dump(self, path: str | Path) -> None:
        """事件序列落盘 jsonl（一行一个事件）。"""
        with open(path, "w", encoding="utf-8") as f:
            for e in self.events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")


def run_chat_with_trace(text: str, session_id: str = "default", *, store=None) -> tuple[Any, list[dict]]:
    """跑一轮真实会话 + 返回完整事件序列（(ChatResult, events)）。

    - graph：带 Recorder 的调度图（parallel=True，绕过指纹缓存直连组装）
    - store：可注入假存储（测试）；默认 xiao_wen.memory
    """
    from xiao_wen import session as _session
    from xiao_wen.graph_builder import build_supervisor_graph

    rec = Recorder()
    rec.record({"type": "input", "text": text, "session_id": session_id})
    graph = build_supervisor_graph(recorder=rec)
    result = _session.chat(text, session_id=session_id, graph=graph, store=store, recorder=rec)
    return result, rec.events
