"""pytest 公共配置：把 homework/ 加进 sys.path，并保证测试不碰真实数据文件"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "homework"))


@pytest.fixture(autouse=True)
def _isolate_memory(tmp_path, monkeypatch):
    """所有测试的记忆都落到临时目录，绝不读写 data/memory.json（真实数据隔离）"""
    import memory_store
    monkeypatch.setattr(memory_store, "MEMORY_PATH", tmp_path / "memory.json")
    yield
