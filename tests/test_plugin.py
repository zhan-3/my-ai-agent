"""子 Agent 注册中心测试：AST 元数据渐进披露（不 exec）、懒加载、内置优先、热插拔动态发现

对应原要求：动态发现 / 自动扫描注册 / 懒加载（未使用不加载）/ 渐进式披露（意图识别阶段仅加载元数据）
"""

from xiao_wen import plugin_registry as reg


def test_discover_reads_metadata_without_executing(tmp_path, monkeypatch):
    # 构造一个「加载即爆炸」的假子 Agent：如果 discover 执行了它，直接抛异常
    monkeypatch.setattr(reg, "AGENT_DIR", tmp_path)
    monkeypatch.setattr(reg, "PLUGIN_DIR", tmp_path)
    (tmp_path / "boom.py").write_text(
        "raise RuntimeError('discover 不应该执行子 Agent 代码！')\nINTENT = '爆炸'\nDESCRIPTION = 'x'\n",
        encoding="utf-8",
    )
    found = reg.discover()
    assert len(found) == 1
    assert found[0]["INTENT"] == "爆炸"  # AST 能读到元数据，但代码从未执行


def test_discover_finds_six_builtin_subagents():
    """内置六子 Agent 零加载发现（多 Agent 主管认识的实体清单）"""
    found = reg.discover()
    builtin = [m for m in found if m["source"] == "builtin"]
    intents = {m["INTENT"] for m in builtin}
    assert intents == {"行程规划", "偏好记录", "历史查询", "知识问答", "联网查询", "其他"}
    # 每项都带可进意图识别 prompt 的描述
    assert all(m["DESCRIPTION"] for m in builtin)


def test_discover_merges_external_extensions():
    """外部扩展（plugins/）在意图不冲突时并入：差旅统计成为第七意图"""
    intents = {m["INTENT"] for m in reg.discover()}
    assert "差旅统计" in intents
    assert len(intents) == 7


def test_builtin_takes_priority_over_external(tmp_path, monkeypatch):
    """内置优先：外部扩展与内置同意图 → 外部被忽略（防意图撞车）"""
    monkeypatch.setattr(reg, "PLUGIN_DIR", tmp_path)
    (tmp_path / "dup.py").write_text("INTENT = '行程规划'\nDESCRIPTION = '外部重复实现'\n", encoding="utf-8")
    found = reg.discover()
    matching = [m for m in found if m["INTENT"] == "行程规划"]
    assert len(matching) == 1
    assert matching[0]["source"] == "builtin"


def test_load_agent_is_lazy_and_cached(monkeypatch):
    """懒加载 + 缓存：派发时才 import，未使用的子 Agent 不加载（哨兵只打印一次）"""
    monkeypatch.setattr(reg, "_loaded", {})
    mod = reg.load_agent("行程规划")
    assert hasattr(mod, "run")
    assert mod.INTENT == "行程规划"
    # 缓存：第二次不重新 exec
    assert reg.load_agent("行程规划") is mod


def test_load_external_agent_run_contract():
    """外部扩展子 Agent（差旅统计）可懒加载，统一接口 run(state) -> dict"""
    mod = reg.load_agent("差旅统计")
    assert hasattr(mod, "run")
    out = mod.run({"user_input": "统计一下出差次数"})
    assert isinstance(out, dict) and "answer" in out


def test_hot_extension_add_is_discovered(tmp_path, monkeypatch):
    """热插拔：运行中新增外部子 Agent → 重新 discover 自动注册（动态发现的灵魂）"""
    monkeypatch.setattr(reg, "AGENT_DIR", tmp_path)
    monkeypatch.setattr(reg, "PLUGIN_DIR", tmp_path)
    (tmp_path / "a.py").write_text("INTENT = '差旅统计'\nDESCRIPTION = 'd'\n", encoding="utf-8")
    assert [m["INTENT"] for m in reg.discover()] == ["差旅统计"]
    # 运行中新增第二个
    (tmp_path / "b.py").write_text("INTENT = '报销提醒'\nDESCRIPTION = 'd2'\n", encoding="utf-8")
    assert {m["INTENT"] for m in reg.discover()} == {"差旅统计", "报销提醒"}
