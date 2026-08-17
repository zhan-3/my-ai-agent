# 主管 Agent Loop

Status: ready-for-agent
Type: spec
Feature: agent-loop

## 目标

把当前一次性 `classify → route → execute → merge` 主管 Workflow 替换为有界 Agent Loop，
保留注册中心和现有子 Agent。主管在一次运行内可以调用子 Agent、观察结果、继续决策、追问或结束。

## 核心流程

```text
用户输入 → decide → 调用子 Agent → observe → decide → ... → final
```

注册中心 manifest 是主管的动态可调用清单。行程子 Agent 内部继续使用 `collect-then-compose`；
政策 RAG、天气、票务和写回验证仍由确定性代码强制执行。

## 成功标准

- 一次运行支持零次、一次或多次子 Agent 调用。
- 每次调用及 observation 进入持久 transcript，并回送下一次决策。
- 支持追问和工具失败后的重试、降级或终止；请求取消不提交不完整结果。
- 步数、时间、token 和重复调用均有硬上限。
- 同步与 SSE 消费同一事件模型，不泄露 LangGraph 节点名。
- 最终策略门拒绝无证据政策、猜测天气和越界票务事实。
- Web 入口切换后删除旧主管运行时，不长期双轨。

## 测试原则

保留领域不变量、用户隔离、持久化和子 Agent 契约测试。新 Loop 接口覆盖同一行为后，删除只验证
固定路由、内部 State、节点名和内部 SSE 阶段的旧测试；不叠加两套等价编排测试。

## 非目标

- 重写现有子 Agent 或注册中心。
- 拆散行程 `collect-then-compose` 深模块。
- 无界自治、多实例协调、完整 Pi Session 树或编码工具生态。
- 第一阶段不实现 steering/follow-up 消息队列、分支导航或自动上下文压缩。

## 票据

| 票据 | 内容 | 状态 |
|---|---|---|
| `issues/01-runtime.md` | Agent Loop、子 Agent 调用适配与事件模型 | ready-for-agent |
| `issues/02-cutover-and-test-prune.md` | Web 切换、旧 Workflow 删除与测试替换 | needs-triage |
