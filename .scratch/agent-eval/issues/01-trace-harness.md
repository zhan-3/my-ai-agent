# 01 — trace 采集 + eval 统一 harness（规则/结构层）

**What to build:** 让 eval 从「只跑意图集」升级为「统一 harness + 失败可回放」：
1. `TraceRecord`（pydantic）采集：input/recent → classify → dispatch(agent 名) → 每 agent 入参/出参 → tool calls → final → memory 写回
2. 插桩点：`graph_builder._make_node`（评测开关 `EVAL_TRACE=1` 时包 recorder，生产路径零改动）+ `session.chat()` 包装（写回与 ChatResult）
3. `src/xiao_wen/eval/` 纯函数校验器扩展：意图相等/subtasks 精确匹配（已有）+ 结构层（plan.days 数量/日期可解析/要素集合覆盖）——延续「CLI 不放逻辑」哲学
4. `scripts/eval/run.py`：`--sets` 支持（intent 起步）、每用例落 `eval_runs/<case_id>/trace.jsonl` + `metrics.json` + `errors.jsonl` + `report.md`（总准确率 + 混淆矩阵 + per_intent）

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] `src/xiao_wen/eval/trace.py`：TraceRecord 模型 + `_make_node` recorder 包装（env 开关）+ chat 包装（recent/写回/契约输出）
- [ ] `src/xiao_wen/eval/metrics.py`：结构层校验器（days 数/日期/要素集合）+ 意图混淆矩阵
- [ ] `scripts/eval/run.py`：--sets 分发 + trace 落盘 + report.md 生成
- [ ] 测试：TraceRecord 结构单测、校验器纯函数单测（可注入假 plan）、trace 采集集成（假 store 注入 `session.chat`，断言事件序列）
- [ ] 门禁全绿：ruff + pytest -m "not integration" + mypy；黄金集 84 条仍 100%

**Out of scope（后续票）:** judge.py（#2）、模拟器产样本（#3）、embedding 意图层（#4）、CI master push 接入。

## 实现提示

- 插桩用 `EVAL_TRACE` env 或显式 recorder 参数，默认关闭；`_make_node` 已是懒加载代理，包一层即可
- trace 事件一行一个 JSON（jsonl），不嵌套大对象（每 agent 出参截断到可判定的字段：answer/plan 契约校验后）
- 意图集直接受益：run.py 现有 `_collect` 逻辑迁移进新 sets 框架，行为不变
