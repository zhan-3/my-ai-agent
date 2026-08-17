# 07 — 收口产品事实、文档与数据库运行基线

**Status:** ready-for-agent
**Blocked by:** 02, 04, 05, 06
**Type:** task
**Feature:** convergence

## 背景

固定车次/票价、测试数量、入口、前端形态、内存后端和 Postgres 版本在代码与文档中互相冲突。
最后一票负责删除过期缓存并记录本迭代真实交付边界。

## What to build

- 删除用户可见预算中的固定车次、站点和固定票价；交通预算改为明确的估算档或不提供数字。
- 12306 结果只保留官方链接、官方站点解析、日期校验和明确能力边界。
- 建立简短能力矩阵：实时事实、政策事实、估算、模型建议、不可执行操作。
- README 只保留快速开始、能力边界、部署入口和关键文档指针；删除完整文件树与手写测试总数。
- 更新 `.env.example`、Docker 注释、`docs/test-map.md`、`docs/layer-map.html` 和相关 ADR。
- 固定 Compose 与 CI 的同一 PostgreSQL major 版本；记录现有卷升级兼容性。
- 提供幂等的专用测试库初始化命令，使 AGENTS 中的测试步骤在干净环境可执行。
- 明确当前支持单实例；migration、连接池与多实例一致性记录为后续演进，不伪装已完成。

## 验收

- [ ] `rg` 不再发现用户可见固定车次/票价、`xiao_wen.system` 或 InMemory 兜底说明。
- [ ] README、环境模板、Docker、ADR 和能力矩阵对 Postgres、前端和模型描述一致。
- [ ] Compose 与 CI 使用同一固定 PostgreSQL major。
- [ ] 新环境按文档可创建 `xiao_wen_test` 并运行门禁，不会回退清理开发库。
- [ ] 文档不手写易漂移的测试数量；需要时由命令或生成报告展示。
- [ ] `scripts/gate.sh` 通过；有有效凭据时运行 `--full` 并记录分层结果。

## 不做

- 不在本票引入 migration 框架或连接池；先固定版本和运行约束。
- 不实现车票查询、购买、余票、实时票价或订单能力。
