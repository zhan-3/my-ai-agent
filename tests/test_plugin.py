"""插件注册中心测试：AST 元数据渐进披露（不 exec）、懒加载、热插拔动态发现"""
from pathlib import Path

import plugin_registry as reg


def test_discover_reads_metadata_without_executing(tmp_path, monkeypatch):
    # 构造一个「加载即爆炸」的假插件：如果 discover 执行了它，直接抛异常
    (tmp_path / "boom.py").write_text(
        "raise RuntimeError('discover 不应该执行插件代码！')\n"
        "INTENT = '爆炸'\nDESCRIPTION = 'x'\n", encoding="utf-8")
    monkeypatch.setattr(reg, "PLUGIN_DIR", tmp_path)
    found = reg.discover()
    assert len(found) == 1
    assert found[0]["INTENT"] == "爆炸"   # AST 能读到元数据，但代码从未执行


def test_discover_real_plugins():
    """真实插件目录（基线三件套）零加载发现"""
    found = reg.discover()
    intents = {p["INTENT"] for p in found}
    assert {"知识问答", "联网查询", "差旅统计"} <= intents


def test_load_plugin_is_lazy_and_cached(monkeypatch):
    monkeypatch.setattr(reg, "_loaded", {})
    mod = reg.load_plugin("联网查询")
    assert hasattr(mod, "run")
    # 缓存：第二次不重新 exec（哨兵只打印一次）
    assert reg.load_plugin("联网查询") is mod


def test_hot_plugin_add_is_discovered(tmp_path, monkeypatch):
    """热插拔：新增插件文件 → 重新 discover 自动注册（动态发现的灵魂）"""
    monkeypatch.setattr(reg, "PLUGIN_DIR", tmp_path)
    (tmp_path / "a.py").write_text(
        "INTENT = '差旅统计'\nDESCRIPTION = 'd'\n", encoding="utf-8")
    assert [p["INTENT"] for p in reg.discover()] == ["差旅统计"]
    # 运行中新增第二个插件
    (tmp_path / "b.py").write_text(
        "INTENT = '报销提醒'\nDESCRIPTION = 'd2'\n", encoding="utf-8")
    assert {p["INTENT"] for p in reg.discover()} == {"差旅统计", "报销提醒"}
