"""记忆层单元测试：短期追加/最近 N 轮、偏好追加/覆盖、常驻城市、历史行程、常用目的地"""
import xiao_wen.memory as ms


def test_add_and_format_recent_messages():
    ms.add_message("user", "你好")
    ms.add_message("assistant", "有什么可以帮你")
    ms.add_message("user", "去北京开会")
    recent = ms.format_recent_messages(n=2)
    assert "去北京开会" in recent
    assert "你好" not in recent  # n=2 只留最近两轮


def test_preference_add_then_update_overrides_same_category():
    # 新增偏好（追加）
    ms.add_or_update_preference("住宿", "喜欢安静", is_update=False)
    assert len(ms.get_preferences("住宿")) == 1
    # 覆盖：同类别更新（如「我现在常住上海」）→ 替换旧条目，不新增
    ms.add_or_update_preference("常驻城市", "上海", is_update=True)
    recs = ms.get_preferences("常驻城市")
    assert len(recs) == 1
    assert recs[0]["content"] == "上海"
    # 新类别追加，旧类别仍在（追加/覆盖互不影响）
    assert len(ms.get_preferences()) == 2


def test_home_city():
    assert ms.get_home_city() is None
    ms.add_or_update_preference("常驻城市", "上海", is_update=True)
    assert ms.get_home_city() == "上海"


def test_itinerary_and_common_destinations():
    assert ms.get_itineraries() == []
    ms.add_itinerary({"to_city": "北京"}, "去北京开会")
    ms.add_itinerary({"to_city": "北京"}, "再去北京培训")
    ms.add_itinerary({"to_city": "杭州"}, "去杭州出差")
    dests = ms.get_common_destinations(n=2)
    assert dests[0] == "北京"
    assert len(dests) == 2
    assert len(ms.get_itineraries()) == 3


def test_load_memory_survives_corrupt_file(tmp_path, monkeypatch):
    """记忆文件被清空/写坏时 load_memory 应兜底重置，绝不抛 JSONDecodeError（回归）"""
    monkeypatch.setattr(ms, "MEMORY_PATH", tmp_path / "memory.json")
    (tmp_path / "memory.json").write_text("", encoding="utf-8")   # 0 字节空文件
    assert ms.load_memory() == {"preferences": [], "itineraries": [], "messages": []}
    (tmp_path / "memory.json").write_text("{not json!!", encoding="utf-8")  # 非法 JSON
    assert ms.load_memory() == {"preferences": [], "itineraries": [], "messages": []}
