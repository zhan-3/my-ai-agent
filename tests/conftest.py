"""pytest 公共配置：把 src/（src 布局包）加进 sys.path，并保证测试不碰真实数据文件"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture(autouse=True)
def _isolate_memory():
    """所有测试的记忆都落到全新 InMemoryBackend（测试隔离：绝不共享/读写真实存储）"""
    import xiao_wen.memory as memory_store

    memory_store.set_backend(memory_store.InMemoryBackend())
    yield
    memory_store._backend = None  # 恢复惰性分派（避免残留 backend 污染后续测试）
