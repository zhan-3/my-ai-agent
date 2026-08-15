# 02 — 图门 clarify_gate

**What to build:** 主管图在 classify_intent 与路由之间加消歧门：命中反问 → 短路到 END（answer=反问问题，plan=None）；未命中 → 原路由不变（单意图字符串路由 / 多意图 Send fan-out）。SSE 阶段事件不暴露内部节点。

**Blocked by:** 01

**Status:** resolved

- [ ] `graph_builder.py`：State 加 `clarify` 字段；`clarify_gate` 节点 + 条件边（`__clarify_end__` → END）；serial/parallel 两图都接
- [ ] `session.py`：`_stage_event` 忽略 `clarify_gate`
- [ ] 测试：图结构含 clarify_gate（两图）、路由函数纯逻辑（命中/未命中/多意图 Send 不变）
- [ ] 集成：真实 LLM 多轮——「查航班」→ 反问含①②；答「②」→ 进行程规划追问

## Answer

已实现并验证：图门 + 路由 + 集成多轮（①直答/②行程规划），单测与集成通过。

## Answer

已实现并验证：clarify_gate 节点 + 条件边短路（serial/parallel），SSE 不露内部节点；
集成多轮通过——查航班→反问①②，②→行程规划，①→确定性直答暂不支持。
