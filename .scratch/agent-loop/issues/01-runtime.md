# 01 — 有界主管 Agent Loop

Status: ready-for-agent

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
