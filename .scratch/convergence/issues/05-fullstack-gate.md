# 05 — 建立全栈质量门禁与容器 smoke test

**Status:** ready-for-agent
**Blocked by:** 04
**Type:** task
**Feature:** convergence

## 背景

当前门禁只覆盖 Python；前端测试、构建、OpenAPI 契约和容器运行结果不会阻止合并。

## What to build

- 为前端增加正式的 `test` script，固定为非交互 `vitest run`。
- 在 `scripts/gate.sh` 中加入前端 lint、test、build，保持失败快速、输出可定位。
- CI 配置固定 Node 与 pnpm 版本，使用 lockfile 缓存并执行同一组前端命令。
- 提供无需启动开发服务器的 OpenAPI schema 生成方式；生成后工作区有差异则失败。
- Docker job 构建后启动 app + Postgres，执行根页面、静态资源、存活和就绪 smoke test。
- CI 明确展示 integration `passed`、`not-run` 或 `operational-failure`，不把缺密钥跳过计作通过。

## 验收

- [ ] 本地 `scripts/gate.sh` 一条命令覆盖后端和前端快速门禁。
- [ ] 31 个现有前端测试通过，lint warning 有明确处置策略。
- [ ] 修改后端契约但未更新生成文件时 CI 失败。
- [ ] 缺失前端产物或 RAG 文档时容器 smoke test 失败。
- [ ] CI 与本地命令使用相同脚本，避免两套门禁漂移。

## 不做

- 不把真实 LLM 测试放到 fork PR。
- 不追求全仓统一覆盖率数字；先保证关键路径进入门禁。

