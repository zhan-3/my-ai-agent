# 08 — 单后端化：删 InMemory，记忆只有 Postgres

**What to build:** 用户决定：记忆只有一个后端（Postgres）。删除 `InMemoryBackend` 与 env 演示兜底；
单元测试强制连真实 Postgres（CI unit job 已带 postgres:16 服务 + POSTGRES_TEST_URL，零 CI 改动）。

**改动面：**
- `memory.py`：删 InMemoryBackend 类 + env 分派兜底；保留 MemoryBackend 协议 + 模块函数 +
  `_backend`/`set_backend` 注入缝（测试用）；`_get_backend()` 无 POSTGRES_URL → 明确报错（不再静默内存兜底）
- `conftest.py`：autouse 隔离 fixture 改为真实 Postgres（POSTGRES_TEST_URL 优先，其次 POSTGRES_URL；
  都没有 → pytest.fail 带起库指引）；每测试前 `clear_all()` 清三张表
- `tests/test_memory_backend.py`：协议/隔离测试改打真实 PG；删 env 分派测试
- `stability.py` 健康检查：删「内存后端」分支，始终探活 Postgres（无 URL → ⚠️）
- 文档：README/HANDOFF/AGENTS.md（门禁前先起 Postgres）

**安全：** 测试优先用 POSTGRES_TEST_URL（独立 xiao_wen_test 库），绝不默认碰开发库；clear_all 只清
messages/preferences/itineraries 三张表。

**Blocked by:** None

**Status:** ready-for-agent

## Answer

已实现并验证（191 非集成全绿，黄金 100%）。
- memory.py：删 InMemoryBackend + env 兜底；唯一后端 Postgres（缺 URL 明确报错）
- conftest：autouse 隔离改为真实 Postgres（TEST_URL 优先，clear_all 清三张表，缺 URL pytest.fail 带指引）
- test_memory_backend：协议/隔离改打真实 PG + 缺 URL 报错测试；stability 删内存分支（缺配 → ⚠️）
- 顺带修 docker-compose.yml：postgres 18+ 要求卷挂 /var/lib/postgresql（旧布局拒启）
- auth 的 InMemoryUserStore 同款兜底保留（未在本次范围，待用户决定）
