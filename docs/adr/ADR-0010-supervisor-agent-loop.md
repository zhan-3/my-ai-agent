# ADR-0010：主管采用有界 Agent Loop，保留子 Agent

- 状态：已接受（2026-08）
- 相关：ADR-0002（会话循环）、ADR-0003（行程规划）、ADR-0005（子 Agent 注册表）、ADR-0009（对话线程）

## 背景

当前主管执行一次 `classify → route → execute → merge` 后结束。它可以拆分多意图并保存对话状态，
但不能根据子 Agent 的真实结果继续决策，因此仍是有状态 Workflow，而不是真正的 Agent。

继续增加条件边、State 字段和特例节点只会扩大固定 Workflow；它不能形成 Pi 风格的
`decide → act → observe → decide` 运行模型。

## 决策

主管升级为有界 Agent Loop，同时保留注册中心和现有子 Agent：

1. 注册中心 manifest 生成主管可调用的子 Agent 清单；子 Agent 继续使用统一执行契约并保持懒加载。
2. 每一步由主管模型选择：直接结束、调用子 Agent、根据 observation 继续、追问用户或明确失败。
3. 子 Agent 输出作为结构化 tool result 写入 transcript，再进入下一次主管决策。
4. 行程子 Agent 内部继续使用既有 `collect-then-compose`，Loop 不拆散领域深模块。
5. Loop 必须限制步骤、时间、token 和重复调用；请求取消时停止运行且不提交不完整结果。
6. 政策证据、天气失败、12306 和写回前验证由确定性策略门执行；主管文本不能覆盖策略门结果。
7. 对外以一个深接口承载运行：`prompt/stream(turn) -> AgentEvent`。Loop 内部消息、调度和持久化
   不扩散到 Web、前端或子 Agent 接口。

## 测试决策

测试面从固定 LangGraph 拓扑迁移到 Agent Loop 接口：

- 保留领域事实、安全、隔离、持久化和子 Agent 契约测试。
- 新增直接结束、单/多子 Agent 调用、observation 回送、故障选择、有界终止和 transcript 生命周期测试。
- 新接口覆盖同一行为后，删除只断言节点名、固定路由、内部 State 字段和内部 SSE 阶段的旧测试。
- 采用“替换，不叠加”；旧 Workflow 测试只在旧入口仍服务生产期间保留。

## 后果

子 Agent 和领域模块可渐进迁移，不需要一次性重写。主管控制流从预定义 DAG 变为模型驱动 Loop，
因此可观察轨迹、预算、取消语义和确定性策略门成为必需能力。当前图工厂可在迁移期作为旧入口保留，Loop
接管 Web 入口并通过验收后删除，不长期维护双运行时。
