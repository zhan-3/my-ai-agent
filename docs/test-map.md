# 测试与门禁

测试保护领域不变量和稳定接口，不冻结内部调度拓扑。主管入口已由 Agent Loop 接管，编排测试统一
通过 Loop 与会话接口验证。

## 提交前门禁

测试只接受专用 PostgreSQL 测试库，不回退开发库：

```bash
scripts/init_test_db.sh
export POSTGRES_TEST_URL=postgresql://postgres:123456@localhost:5432/xiao_wen_test
scripts/gate.sh
```

`scripts/gate.sh` 只执行四项确定性后端检查：

1. Ruff lint
2. Ruff format check
3. 非 integration pytest
4. mypy

前端 lint/test/build 由 CI 独立执行，避免每次后端迭代都重复构建前端。OpenAPI 漂移只在 HTTP
契约变化时按需检查；镜像 smoke 只在主分支或手动 CI 中运行。

## 按需验证

这些命令不是日常提交门禁，只有对应行为发生变化时才运行：

```bash
# 前端改动
pnpm --dir frontend lint
pnpm --dir frontend test
pnpm --dir frontend build

# HTTP 契约改动
pnpm --dir frontend gen:api
git diff --exit-code -- frontend/src/api/schema.generated.ts

# 真实模型或 Embedding 接缝改动
uv run pytest -q -m "integration and not external_live"

# 发布镜像
scripts/smoke_image.sh xiao-wen:ci
```

真实模型与第三方实时检查只用于诊断。它们的波动、成本或供应商故障不得伪装成确定性门禁
失败，也不得被报告成产品发布成绩。

## 对话细节回归集

实机测试曾反复暴露「对话细节」漏洞（纯要素列举被拒、修改已有行程不被子 Agent 接收、
英文思维链泄漏、应急块粘连、政策原文链接缺失等）。这些漏洞的根因在主管 LLM 的派发与
提取判断，无法被确定性单元测试覆盖。

`tests/test_dialogue_regression.py` 把每个已修复的对话漏洞固化为一条例：断言结构化
outcome（intent / plan / 落库状态 / 无思维链泄漏），不锁定模型措辞。

维护约定：每修一个对话细节漏洞，就在该文件补一条对应用例，形成「漏洞 → 修复 → 回归」
闭环，避免同类问题靠下一次实机测试才暴露。

```bash
uv run pytest -q -m "integration" tests/test_dialogue_regression.py
```

约 2 分钟 / 4 用例，真实 LLM；不进确定性门禁，对话/意图/编排行为变化后按需回归。

## 长期保留的安全网

以下测试保护领域事实和安全约束，架构迁移时继续保留：

- 政策结论必须携带本轮 RAG 证据
- 天气失败显式呈现
- 行程缺项、日期、天数和写回前验证
- JWT 用户隔离、对话线程隔离和长期记忆所有权
- PostgreSQL 持久化语义
- 配置、密钥和 readiness 语义
- 子 Agent 注册、懒加载和统一执行契约

## Agent Loop 测试面

主管 Loop 通过其小接口验证：

- 模型可直接结束，也可调用一个或多个子 Agent
- 子 Agent 结果以 observation 回到下一次决策
- 工具失败后可重试、降级、追问或明确失败
- 步数、时间、token 和重复调用都有界
- transcript 持久化 `assistant/tool_call/tool_result`
- 请求取消会停止运行且不提交不完整结果
- 最终策略门不能把无证据政策、天气失败或票务猜测改写成成功

旧 LangGraph 主管节点、固定路由、内部 State 与节点名 SSE 测试已经退役；不维护双运行时或双测试套件。
