"""调度优化模块（薄壳）：并行调度图入口 + 演示
跑法：uv run python -m xiao_wen.scheduler
依赖：xiao_wen.plugin_registry（子 Agent 注册表，懒加载子 Agent）

本模块只做两件事：
- app = 图工厂的调度图实例（build_supervisor_graph(parallel=True)）——产品默认图
  （session.chat），多意图并行走 Send fan-out/fan-in；图组装收口于 xiao_wen.graph_builder
- __main__ 演示：单意图回归 + 多意图并行

并行组件（dispatch / make_parallel / merge）随建图代码迁入 graph_builder（导出，
可独立测试）——本模块不再重复实现。
"""

from xiao_wen.graph_builder import build_supervisor_graph

app = build_supervisor_graph(parallel=True)

# ---- 演示：单意图回归 + 多意图并行 ----
if __name__ == "__main__":
    from xiao_wen.session import chat

    demo = [
        # ① 单意图回归（subtasks 为空 → 原路由，不破坏）
        "10月8日去北京开会4天",
        # ② 多意图并行：知识问答 + 联网查询
        "帮我查下出差住宿标准是什么，顺便看看北京今天天气怎么样",
        # ③ 多意图并行：历史查询 + 联网查询
        "我上次的行程是什么，还有上海明天天气怎么样",
        # ④ 边界单意图
        "这个暑假去哪里玩",
    ]
    for t in demo:
        print("=" * 60)
        print(f"用户：{t}")
        r = chat(t, graph=app)
        print(f"意图：{r.intent}（{r.reason}）")
        # 拆分/并行信息体现在合并回答开头（“⚡ 同时为你处理了 N 个请求”）
        print(r.answer)
