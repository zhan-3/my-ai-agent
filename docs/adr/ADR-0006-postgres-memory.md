# ADR-0006：会话隔离 + Postgres 存储后端

- 状态：已接受（2026-08）
- 相关：ADR-0002（会话循环，session_id 预留"暂缓"）、ADR-0005（插件注册表）

## 背景

记忆模块（memory.py）一直是**全局单文件**（data/memory.json）：`session.chat` 的
session_id 参数只占位（ADR-0002 明说"会话隔离暂缓"）。多人/多会话共用一份记忆，
偏好、历史行程、短期对话互相串写。

## 决策

1. **会话隔离**：所有记忆按 `session_id` 隔离（默认 `"default"` 向后兼容既有调用点）。
   session_id 全链路贯穿：webapp → `session.chat` → 图 State → 子 Agent（preference/
   history 从 State 取，`state.get("session_id", "default")` 兜底）→ memory 函数。
2. **存储后端协议**：memory.py 定义 `MemoryBackend`（8 个基础读写方法，三个域：
   消息/偏好/行程），两个实现——
   - `InMemoryBackend`：进程内存，无 `POSTGRES_URL` 时的演示/测试兜底（重启即失）
   - `PostgresBackend`（memory_pg.py）：psycopg 直连，三张表（messages/preferences/
     itineraries）各带 session_id 列 + `WHERE session_id = %s` 过滤，幂等建表
3. **env 分派**：`_get_backend()` 惰性读 `POSTGRES_URL`——有则 Postgres（产品），无则
   InMemory（演示）。`set_backend()` 供测试注入（替代旧的 `MEMORY_PATH` monkeypatch）。
4. **测试策略**：单元测试注入全新 `InMemoryBackend`（零外部依赖）；Postgres 真库测试
   标 `@pytest.mark.postgres`（本地有容器/原生 PG 且设 `POSTGRES_TEST_URL` 才跑）。

## 为什么不选别的

- **不选 LangGraph checkpointer**：当前无"中断会话随时恢复"需求；checkpointer 是另一
  套记忆范式（thread 维度自动快照），改造要动图编译与全部 e2e，收益无需求支撑。
- **不选 PostgresStore（语义搜索）**：记忆层检索全部结构化（category 精确查询、常用
  目的地统计），无语义搜索需求；语义搜索只在 RAG（Chroma，独立模块）。
- **不选 MySQL**：LangGraph 生态生产路径是 Postgres；记忆层虽不需要向量，但 JSONB +
  单库原则 + 官方 checkpointer/store 后路都指向 Postgres。Redis 是缓存角色，当前无
  明确需求，不引第二个基础设施组件。

## 后果

- 演示（无 POSTGRES_URL）记忆为进程内存，重启即失（README 注明）。
- 产品形态一条 env：`POSTGRES_URL=postgresql://...` 即持久化 + 会话隔离。
- JSON 文件后端删除（load_memory/save_memory/MEMORY_PATH 及损坏兜底测试随删）。
- 未来产品化若需"随时恢复"或"记忆语义检索"，可平滑加 checkpointer/PostgresStore
  （同一 Postgres，连接串/表结构兼容演进）。
