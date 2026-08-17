# 01 — 统一运行时配置与 JWT 启动校验

**Status:** ready-for-agent
**Blocked by:** None
**Type:** task
**Feature:** convergence

## 背景

`auth.py` 在 dotenv 加载前读取 `JWT_SECRET`，其他模块分散调用默认 `load_dotenv()`。这既不能
保证 `.env` 优先，也允许空密钥或公开开发密钥进入运行时。

## What to build

- 建立单一配置模块，提供小接口 `load_settings() -> Settings`。
- 在模块内部执行一次 `.env` 加载，明确使用 `.env` 覆盖继承变量。
- 懒校验 LLM/Embedding 配置，保持模块导入不因缺少模型密钥失败。
- Web 应用启动时校验 `POSTGRES_URL` 和 JWT 密钥；空值、短密钥、公开默认密钥必须失败。
- 保持当前已配置模型；不得在错误时切换模型、网关或密钥。
- `auth`、`llm`、`rag`、`stability` 和脚本通过该接口读取配置，删除分散 dotenv 初始化。

## 接口约束

- 调用方只依赖类型化 Settings 和明确错误，不理解 dotenv 顺序。
- 测试可注入环境或 Settings，不新增只有一个实现的配置 adapter。
- 日志与健康检查只报告配置是否存在，不输出密钥值。

## 验收

- [ ] `.env` 值覆盖同名继承环境变量的测试通过。
- [ ] `auth` 不会在 dotenv 初始化前冻结 JWT 密钥。
- [ ] 空/短/公开 JWT 密钥的 Web 启动校验失败且错误可读。
- [ ] `test_import_does_not_read_env` 等懒加载测试保持通过或按新接口等价更新。
- [ ] `scripts/gate.sh` 通过。

## 不做

- 不更换模型、密钥或供应商。
- 不引入外部 secrets manager。

