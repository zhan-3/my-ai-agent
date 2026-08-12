"""完整系统模块（薄壳）：单意图主管图入口 + 演示
跑法：uv run python -m xiao_wen.system
依赖：.env（DEEPSEEK_* + DASHSCOPE_API_KEY）；xiao_wen.memory（记忆，短期+长期两层）
      xiao_wen.rag（向量知识问答）、xiao_wen.web（联网查询图）

本模块只做两件事：
- app = 图工厂的单意图实例（build_supervisor_graph(parallel=False)）——图组装收口于
  xiao_wen.graph_builder（深模块），本模块是消费方薄壳
- __main__ 演示：三类案例端到端（偏好/常驻城市 → 行程规划 → 联网 → 历史 → 外部扩展 → 边界）

产品默认图是调度图（session.chat，parallel=True，多意图并行）；本模块的 app 是
「最小主管图」：单意图路径完全兼容（调度图是它的超集），供演示与文档引用。

记忆分层（对应 LangChain 官方 memory 概念）：
- 短期记忆：最近 N 轮对话（memory.messages），每轮 invoke 前注入 —— 对应 checkpointer+thread
- 长期记忆：偏好（含常驻城市，追加/覆盖）、历史行程 —— 对应 store
- hot path 权衡：注入克制（截断最近 6 轮），避免全量历史塞上下文（变慢、变贵、干扰）
"""

from xiao_wen.graph_builder import build_supervisor_graph

app = build_supervisor_graph(parallel=False)

# ---- 演示：三类案例端到端 ----
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
