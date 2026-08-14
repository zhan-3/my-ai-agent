"""pytest 公共配置：把 src/（src 布局包）加进 sys.path，并保证测试不碰真实数据文件

记忆隔离：单后端架构（Postgres）——每个测试前清空三张表并注入全新 PostgresBackend，
绝不共享/读写开发库（优先 POSTGRES_TEST_URL 独立测试库，其次显式 POSTGRES_URL）。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture(autouse=True)
def _isolate_memory(monkeypatch):
    """所有测试落到真实 Postgres（单后端）：每测试前清空记忆三表 + users 表，
    并把 POSTGRES_URL 统一指向测试库（auth 用户存储也走 env 懒构造）"""
    import xiao_wen.memory as memory_store
    from xiao_wen.memory_pg import PostgresBackend, PostgresUserStore

    url = os.environ.get("POSTGRES_TEST_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        pytest.fail(
            "单元测试需要 Postgres（唯一后端）：\n"
            "  1) docker-compose up -d postgres\n"
            "  2) export POSTGRES_TEST_URL=postgresql://postgres:123456@localhost:5432/xiao_wen_test\n"
            "     （CI 已注入 POSTGRES_TEST_URL；测试优先用独立测试库，避免清掉开发库数据）"
        )
    monkeypatch.setenv("POSTGRES_URL", url)  # 统一指向测试库：memory/auth 懒构造都走它
    backend = PostgresBackend(url)
    backend.clear_all()
    PostgresUserStore(url).clear_all()
    memory_store.set_backend(backend)
    yield
    memory_store._backend = None  # 恢复懒构造（避免残留 backend 污染后续测试）
