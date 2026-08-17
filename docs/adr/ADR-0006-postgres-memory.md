# ADR-0006：会话隔离与 Postgres 单后端

- 状态：已接受（2026-08，收敛更新）
- 相关：ADR-0002（会话循环）、ADR-0007（JWT 认证）、ADR-0008（部署）

## 背景

记忆、行程和用户身份必须持久化并按会话隔离。运行时后端、测试数据库和容器版本曾在文档中
存在多种互相冲突的描述，测试还可能在缺少专用连接串时误用开发库。

## 决策

1. 运行时唯一后端为 Postgres，`POSTGRES_URL` 必填；消息、偏好、行程和用户分别存入四张表。
2. 短期消息按线程 `session_id` 过滤；偏好与行程按 `user_id` 过滤。活跃任务表同时校验线程和用户。
3. 当前用 `CREATE TABLE IF NOT EXISTS` 幂等初始化表结构，连接按操作短连接。migration 框架和
   连接池不在本迭代引入。
4. Compose、CI 和镜像 smoke 统一使用 PostgreSQL 16。Compose 数据卷挂载到
   `/var/lib/postgresql/data`。
5. 测试必须显式设置 `POSTGRES_TEST_URL`，不回退到 `POSTGRES_URL`。运行
   `scripts/init_test_db.sh` 可幂等创建 `xiao_wen_test`；测试只清理该专用库。
6. 存活与就绪探针只执行只读 `SELECT 1`，不写入业务表。

## 卷兼容性

此前由浮动镜像标签创建的卷可能属于更高 major，不能由 PostgreSQL 16 原地读取或
降级。需要保留数据时，先用原版本容器执行 `pg_dump`，再导入新的 16 卷；开发环境不保留数据
时可停止服务并删除旧卷。Compose 使用新的 `xw_pg16_data` 名称，避免自动挂载旧卷。

## 后果与后续

- 当前部署明确支持单应用实例；进程内会话锁、图缓存和熔断状态不提供跨实例一致性。
- schema migration、连接池、备份恢复和多实例协调是后续独立工作，不伪装为现有能力。
