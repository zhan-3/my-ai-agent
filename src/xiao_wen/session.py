"""会话循环模块：一轮完整交互的闭环（ADR-0002，取代 webapp/system/scheduler 三处复制）

- chat(text, session_id) -> ChatResult(answer, intent, reason)
  读最近对话（短期记忆）→ 注入 → 主管图 invoke → 写回用户与助手两轮
- 异常向上抛：降级文案是 web 层的职责（webapp 保留 try/except），demo 需要真实异常
- 依赖可注入：graph 默认调度图（build_supervisor_graph(parallel=True)，多意图并行）；
  store 默认 memory 模块（假图/假存储即可测循环）
- 会话隔离：记忆按 session_id 隔离（ADR-0006），webapp 层升级为用户隔离（ADR-0007）
"""

from dataclasses import dataclass

from xiao_wen import memory


@dataclass
class ChatResult:
    answer: str
    intent: str
    reason: str
    plan: dict | None = None  # 结构化行程（slice 1：行程 Agent 产出；非行程为 None）


def chat(text: str, session_id: str = "default", *, graph=None, store=None) -> ChatResult:
    """一轮对话闭环。

    - graph：默认调度图（懒导入 graph_builder，走指纹缓存；多意图并行走 Send fan-out）
    - store：默认 xiao_wen.memory（读 recent / 写回两轮）；可注入假存储
    - session_id：会话维度（webapp 层 = 用户名），记忆按此隔离（ADR-0006 / ADR-0007）
    """
    if graph is None:
        from xiao_wen.graph_builder import build_supervisor_graph

        graph = build_supervisor_graph(parallel=True)
    if store is None:
        store = memory

    recent = store.format_recent_messages(6, session_id=session_id)
    r = graph.invoke(
        {
            "messages": [("human", text)],
            "user_input": text,
            "recent": recent,
            "session_id": session_id,
        }
    )
    store.add_message("user", text, session_id=session_id)
    store.add_message("assistant", r["answer"], session_id=session_id)
    return ChatResult(answer=r["answer"], intent=r["intent"], reason=r["reason"], plan=r.get("plan"))
