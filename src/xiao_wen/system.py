"""完整系统模块：多 Agent 主管总装（注册表驱动的子 Agent 图）
跑法：uv run python -m xiao_wen.system
依赖：.env（DEEPSEEK_* + DASHSCOPE_API_KEY）；xiao_wen.memory（记忆，短期+长期两层）
      xiao_wen.rag（向量知识问答）、xiao_wen.web（联网查询图）

架构（多 Agent：主管 + 可发现的子 Agent）：
- 子 Agent 层：六个内置子 Agent 实体在 src/xiao_wen/agents/（+ 外部扩展 plugins/），
  每个模块声明 INTENT/DESCRIPTION/run(state)，由注册中心（xiao_wen.plugin_registry）
  自动扫描注册、AST 渐进式披露、派发时懒加载——新增子 Agent 主管零改动
- 意图识别：LLM 主管（意图词汇表 = 注册表 manifest 动态生成，含六内置 + 外部扩展）
  + 注入最近对话（短期记忆）；多意图拆分子任务由调度增强（scheduler）并行处理
- 本模块职责：把注册表 manifest 组装成主管图（节点 = 懒加载代理，路由 = manifest 意图）

记忆分层（对应 LangChain 官方 memory 概念）：
- 短期记忆：最近 N 轮对话（memory.messages），每轮 invoke 前注入 —— 对应 checkpointer+thread
- 长期记忆：偏好（含常驻城市，追加/覆盖）、历史行程 —— 对应 store
- hot path 权衡：注入克制（截断最近 6 轮），避免全量历史塞上下文（变慢、变贵、干扰）
"""
from typing import Any, Hashable, TypedDict, Annotated
from langgraph.graph import StateGraph, START, END, add_messages
from langchain_core.messages import AnyMessage

from xiao_wen import intent
from xiao_wen.plugin_registry import discover, load_agent

# ---- 1. State ----
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    recent: str  # 短期记忆：最近对话（每轮 invoke 前注入）
    intent: str
    reason: str
    answer: str

# ---- 2. 主管：意图分类（单一来源 xiao_wen.intent，词汇表 = 注册表 manifest） ----
def classify_intent(state):
    r = intent.classify(state["recent"], state["user_input"])
    # 兜底：LLM 幻觉意图不在词汇表内 → 归「其他」（避免路由 KeyError）
    return {"intent": r.intent, "reason": r.reason}

# ---- 3. 组装主管图（注册表驱动：manifest 动态生成节点 + 路由） ----
manifest = discover()
intent.set_intents(manifest)  # 注入动态意图词汇表（含外部扩展，如 差旅统计）

def _make_node(intent_name: str):
    """懒加载代理节点：派发到该意图时才加载子 Agent 模块（未使用的子 Agent 不加载）"""
    def node(state):
        return load_agent(intent_name).run(state)
    return node

graph = StateGraph(State)
graph.add_node(classify_intent)
ROUTES: dict[Hashable, str] = {}
for m in manifest:
    graph.add_node(m["INTENT"], _make_node(m["INTENT"]))
    ROUTES[m["INTENT"]] = m["INTENT"]

graph.add_edge(START, "classify_intent")
graph.add_conditional_edges("classify_intent", lambda s: s["intent"], ROUTES)
for name in ROUTES.values():
    graph.add_edge(name, END)

app = graph.compile()

# ---- 4. 演示：三类案例端到端 ----
if __name__ == "__main__":
    from xiao_wen.session import chat
    demo = [
        # ① 偏好新增（长期记忆写入）
        "我不吃辣，住宿喜欢安静",
        # ② 常驻城市（长期记忆更新：覆盖同类别）
        "我现在常住上海",
        # ③ 行程规划：不说出发城市 → 用常驻城市上海（别再傻问）
        "10月8日去北京开会4天",
        # ④ 联网查询
        "北京今天天气怎么样？",
        # ⑤ 指代消解：靠短期记忆（最近对话）理解「那上海呢」= 问天气
        "那上海呢",
        # ⑥ 历史查询（读长期记忆）
        "我上次的行程是什么",
        # ⑦ 外部扩展子 Agent：差旅统计（第七意图，由注册表动态发现）
        "统计一下我的出差情况",
        # ⑧ 边界（应归「其他」）
        "这个暑假去哪里玩",
    ]
    for t in demo:
        print("=" * 56)
        print(f"用户：{t}")
        r = chat(t)
        print(f"意图：{r.intent}（{r.reason}）")
        print(r.answer)
