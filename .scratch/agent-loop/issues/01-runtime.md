# 01 — 有界主管 Agent Loop

Status: resolved

实现 `../spec.md` 的核心运行时。注册中心与子 Agent 保持现有统一执行契约；新增适配层把 manifest
暴露为主管可调用清单，并把子 Agent 输出规范化为 observation。

## 验收

- Loop 外部接口保持小：接收线程 turn，流式产生生命周期事件。
- 覆盖 direct final、单次调用、多次调用、失败后决策、追问、请求取消和预算终止。
- transcript 保存 assistant/tool-call/tool-result，下一步能观察结果。
- 策略门覆盖政策证据、天气失败和 12306 边界。
- 现有行程 `collect-then-compose` 与子 Agent 注册/懒加载测试保持通过。

## Comments

- 主管模型驱动下一步，不用增加固定条件边模拟自主。
- 迁移期旧图可作为入口对照，但新接口不依赖 LangGraph 节点名或 State 字段。

## Answer（2026-08-18 完成）

- 实现 `src/xiao_wen/agent_loop.py`：有界 Loop，6 步 / 6 次子 Agent 调用 / 60 秒 / 12K token（字符估算）/ 重复副作用调用拦截。
- 动态工具清单由注册中心 manifest 生成 `agent_N`；子 Agent 输出经 `_normalize_outcome` 规范化为 observation。
- 策略门覆盖政策 RAG 证据、天气失败与 12306 边界；最终回答仅使用已观察结果。
- `tests/test_agent_loop.py` 覆盖 direct final、单次/多次调用、失败后决策、追问、取消、预算终止与 side-effect 拦截。
- 验证：后端门禁 234 passed（8 integration 按需），真实模型集成 7 passed。
