# 01 — trace 采集 + eval 统一 harness（规则/结构层）

**What to build:** 让 eval 从「只跑意图集」升级为「统一 harness + 失败可回放」：
1. `TraceRecord`（pydantic）采集：input/recent → classify → dispatch(agent 名) → 每 agent 入参/出参 → tool calls → final → memory 写回
2. 插桩点：`graph_builder._make_node`（评测开关 `EVAL_TRACE=1` 时包 recorder，生产路径零改动）+ `session.chat()` 包装（写回与 ChatResult）
3. `src/xiao_wen/eval/` 纯函数校验器扩展：意图相等/subtasks 精确匹配（已有）+ 结构层（plan.days 数量/日期可解析/要素集合覆盖）——延续「CLI 不放逻辑」哲学
4. `scripts/eval/run.py`：`--sets` 支持（intent 起步）、每用例落 `eval_runs/<case_id>/trace.jsonl` + `metrics.json` + `errors.jsonl` + `report.md`（总准确率 + 混淆矩阵 + per_intent）

**Blocked by:** None — can start immediately

**Status:** resolved

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

## Answer

已实现并验证（tdd：先写 7 个测试红 → 实现绿 → 门禁全绿）：

- `src/xiao_wen/eval/trace.py`：Recorder（事件列表 + dump jsonl）+ `run_chat_with_trace`（构造带 recorder 的图交给 session.chat，返回 (ChatResult, events)）
- `graph_builder.py`：`build_supervisor_graph(parallel, recorder)`——带 recorder 时绕过指纹缓存直连 `_assemble`（不污染生产缓存）；`_make_classify`/`_make_node` 包 recorder（classify 事件 subtasks 序列化为字符串列表；agent 事件只留白名单键 answer/plan/stats/history）
- `session.py`：`chat(..., recorder=None)` 三处插桩（recent/final/memory_write），默认 None 零开销
- `src/xiao_wen/eval/metrics.py`：+`check_trip_plan`（结构层校验器：plan 缺失/summary 空/days 数量/日期 YYYY-MM-DD/字段齐全/activities 列表；date_is_vague 跳过日期格式）
- `src/xiao_wen/eval/runners.py`：`run_intent_set(cases, classify_fn, verbose)`（迁移 run.py 旧 _collect，classify_fn 可注入）
- `scripts/eval/run.py`：_collect 改调 runners（行为不变）
- 测试 `tests/test_eval_harness.py`（7 个）：完整事件链（假 classify/假 agent 不烧 LLM）、JSON 可序列化、dump jsonl、结构校验器正/反/模糊日期、runner 注入假 classifier

验证：unit 全过 + ruff/format/mypy 全绿；黄金集 84 条仍 100% PASS；真 LLM 冒烟 `run_chat_with_trace("我规划的行程是什么")` 事件链完整（input→classify→agent→final）。

Status: resolved
