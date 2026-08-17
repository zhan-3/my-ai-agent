# 测试与门禁

测试的目标是保护领域不变量和稳定接口，而不是冻结当前 Workflow 的节点拓扑。Agent Loop 接管主管
入口后，应以 Loop 接口测试替换旧编排实现测试；替换完成前不提前删除仍在保护生产路径的用例。

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

# 意图分类行为改动
uv run python scripts/golden_intents.py --set holdout

# 人工审阅的明确意图契约
uv run python scripts/golden_intents.py --threshold 0.90 --min-intent 0.75

# 发布镜像
scripts/smoke_image.sh xiao-wen:ci
```

真实模型与第三方实时检查只用于诊断。它们的波动、成本或供应商故障不得伪装成确定性门禁
失败，也不得被报告成产品发布成绩。评测数据可信边界见 [`tests/data/EVAL.md`](../tests/data/EVAL.md)。

## 长期保留的安全网

以下测试保护领域事实和安全约束，架构迁移时继续保留：

- 12306 官方链接、日期范围和车站歧义
- 政策结论必须携带本轮 RAG 证据
- 天气失败显式呈现
- 行程缺项、日期、天数和写回前验证
- JWT 用户隔离、对话线程隔离和长期记忆所有权
- PostgreSQL 持久化语义
- 配置、密钥和 readiness 语义
- 子 Agent 注册、懒加载和统一执行契约

## Agent Loop 的目标测试面

主管 Loop 落地时，优先通过其小接口验证：

- 模型可直接结束，也可调用一个或多个子 Agent
- 子 Agent 结果以 observation 回到下一次决策
- 工具失败后可重试、降级、追问或明确失败
- 步数、时间、token 和重复调用都有界
- transcript 持久化 `assistant/tool_call/tool_result`
- 请求取消会停止运行且不提交不完整结果
- 最终策略门不能把无证据政策、天气失败或票务猜测改写成成功

新接口覆盖同一行为后，删除只断言 LangGraph 节点名、固定路由、内部 State 字段和 SSE 内部阶段名的
旧测试。遵循“替换，不叠加”：不在新 Loop 测试之上继续维护一套等价的 Workflow 实现测试。
