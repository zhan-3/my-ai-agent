# ADR-0014：测试库强制隔离（POSTGRES_TEST_URL 单一口径）

- 状态：已接受（2026-08，收敛更新）
- 相关：ADR-0006（Postgres 单后端）、ADR-0008（CI 分层）

## 背景

单元测试的唯一后端是 Postgres（ADR-0006 决策 5 已要求测试库）。但历史上存在两类
回退风险：

1. 测试代码里出现过 `POSTGRES_TEST_URL or POSTGRES_URL` 回退分支与
   `pytest.mark.skipif(not pg_url)` 死逻辑——测试库缺失时可能静默落到开发库，
   或在本地环境差异下跳过本应必跑的测试。
2. `.env` 曾建议写入测试库键；若测试代码读取 `.env`，本地开发库与 CI 测试库口径
   会漂移。

`clear_all()` 会在每个测试前清空业务表，若连接串指向开发库（127.0.0.1:55432），
将直接清空开发数据——这是不可逆事故，必须从机制上杜绝。

## 决策

1. **conftest 强制**：`tests/conftest.py` 的 autouse fixture 读取
   `POSTGRES_TEST_URL`，缺失则 `pytest.fail`（提示先跑 `scripts/init_test_db.sh`），
   并 `monkeypatch.setenv("POSTGRES_URL", url)` 把一切懒构造统一指向测试库。
2. **绝不回退**：测试代码只读 `POSTGRES_TEST_URL`；删除历史遗留的
   `or POSTGRES_URL` 回退分支与 skipif 死逻辑。
3. **测试库不写 .env**：`.env.example` 明示「测试库不要写入 .env」；开发库
   （55432）与测试库（compose 5432）物理分离，均 5 张表同构。
4. **幂等建库**：`scripts/init_test_db.sh` 在 compose Postgres 容器上幂等创建
   `xiao_wen_test`；CI 由 service container 直接提供同名库。
5. **每测试隔离**：`clear_all()` 清空业务表 + 注入全新 `PostgresBackend`，yield 后
   恢复 `memory_store._backend = None`，防止残留 backend 污染后续测试。

## 后果

- 测试与开发库零交叉：任何测试路径都不可能写开发库，`clear_all()` 成为安全网而非风险。
- 本地跑门禁的最小动作固定为：`docker compose up -d postgres` +
  `export POSTGRES_TEST_URL=postgresql://postgres:123456@localhost:5432/xiao_wen_test`。
- 代价：测试必须真实连 Postgres（无内存回退），这也是项目「单后端」约束下的预期形态。
