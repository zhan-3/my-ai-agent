"""会话循环模块：一轮完整交互的闭环（ADR-0002，取代 webapp/system/scheduler/smoke 四处复制）

- chat(text, session_id) -> ChatResult(answer, intent, reason)
  读最近对话（短期记忆）→ 注入 → 主管图 invoke → 写回用户与助手两轮
- 异常向上抛：降级文案是 web 层的职责（webapp 保留 try/except），demo/smoke 需要真实异常
- 依赖可注入：graph 默认 system.app；store 默认 memory 模块（假图/假存储即可测循环）
- 会话隔离暂缓：记忆为全局单文件，session_id 仅占位（ADR-0002）
"""

from dataclasses import dataclass

from xiao_wen import memory


@dataclass
class ChatResult:
    answer: str
    intent: str
    reason: str


def chat(text: str, session_id: str = "default", *, graph=None, store=None) -> ChatResult:
    """一轮对话闭环。

    - graph：默认 xiao_wen.system.app（懒导入，避免会话层导入重模块）
    - store：默认 xiao_wen.memory（读 recent / 写回两轮）；可注入假存储
    - session_id：预留的会话维度，记忆隔离暂缓（ADR-0002）
    """
    if graph is None:
        from xiao_wen.system import app as default_graph

        graph = default_graph
    if store is None:
        store = memory

    recent = store.format_recent_messages(6)
    r = graph.invoke(
        {
            "messages": [("human", text)],
            "user_input": text,
            "recent": recent,
        }
    )
    store.add_message("user", text)
    store.add_message("assistant", r["answer"])
    return ChatResult(answer=r["answer"], intent=r["intent"], reason=r["reason"])
