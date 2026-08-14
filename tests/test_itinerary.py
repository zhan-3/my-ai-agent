"""行程规划纯逻辑测试：必填要素缺失检查 + 结果可读性格式 + 管线编排（无需 LLM）

管线（ADR-0003）收口于 xiao_wen.trip_planner：提取 → 常驻城市补全 → 缺项检查 → 生成 → 写回。
"""

from typing import Any

from xiao_wen import trip_planner as _it

TripRequest = _it.TripRequest
ItineraryPlan = _it.ItineraryPlan


def _req(**kw):
    base: dict[str, Any] = {
        "to_city": "北京",
        "from_city": "上海",
        "start_date": "2026-10-08",
        "duration_days": 4,
        "transport": "",
        "hotel_pref": "无",
        "budget_pref": "中等",
    }
    base.update(kw)
    return TripRequest(**base)


# ---------------- 纯函数：缺项检查 ----------------


def test_missing_full_request_is_empty():
    assert _it._missing(_req()) == []


def test_missing_detects_each_field():
    assert "目的城市" in _it._missing(_req(to_city="待定"))
    assert "出发城市" in _it._missing(_req(from_city="未知"))
    assert "出发日期" in _it._missing(_req(start_date=""))
    assert "出差天数" in _it._missing(_req(duration_days=0))
    assert "出差天数" in _it._missing(_req(duration_days=-1))


# ---------------- 纯函数：格式化 ----------------


def test_format_plan_readable_with_reasons():
    day = _it.DayPlan(
        date="2026-10-08",
        transport="高铁 G2 次 07:00 上海虹桥→11:28 北京南",
        hotel="全季酒店（国贸店）",
        activities=["峰会"],
        notes="带好身份证",
    )
    plan = ItineraryPlan(
        summary="10月8日从上海乘高铁赴北京开会4天",
        days=[day],
        reasons=["避开早高峰，选择上午班次"],
    )
    text = _it.format_plan(plan)
    assert "10月8日" in text
    assert "高铁 G2 次" in text  # 每日交通
    assert "💡 安排理由" in text  # 基础项 E：安排理由
    assert "避开早高峰" in text
    assert "带好身份证" in text  # 备注（注意事项）


def test_format_plan_no_reasons_ok():
    plan = ItineraryPlan(summary="行程规划：示例", days=[], reasons=[])
    text = _it.format_plan(plan)
    assert "示例" in text
    assert "💡 安排理由" not in text


# ---------------- 编排：plan()（模型用桩注入） ----------------


class _FakeChain:
    def __init__(self, out):
        self._out = out

    def invoke(self, payload):
        return self._out


def _stub_models(monkeypatch, extract_out, plan_out=None):
    monkeypatch.setattr(_it, "_extract_model", lambda: _FakeChain(extract_out))
    if plan_out is not None:
        monkeypatch.setattr(_it, "_plan_model", lambda: _FakeChain(plan_out))


def test_plan_needs_info_when_missing(monkeypatch):
    """缺项 → NeedsInfo（判别式），缺项短路不调生成"""
    called = {"plan": False}

    def boom():
        called["plan"] = True
        raise AssertionError("缺项短路：不应调用生成")

    _stub_models(monkeypatch, _req(to_city="待定"))
    monkeypatch.setattr(_it, "_plan_model", boom)
    r = _it.plan("去开会")
    assert isinstance(r, _it.NeedsInfo)
    assert r.missing == ["目的城市"]
    assert called["plan"] is False


def test_plan_normalizes_string_duration(monkeypatch):
    """提取 LLM 把缺天数输出成「待定」字符串（曾致 pydantic 校验崩溃、整轮挂掉）
    → plan() 哨兵归一化成 0 → 走缺项检查追问，而不是崩溃"""
    _stub_models(monkeypatch, _req(duration_days="待定"))
    r = _it.plan("去北京开会")
    assert isinstance(r, _it.NeedsInfo)
    assert "出差天数" in r.missing, f"缺天数应被识别为缺项，实际：{r.missing}"


def test_plan_home_city_completes_before_missing_check(monkeypatch):
    """常驻城市补全先于缺项检查：缺出发城市但有常驻城市 → 不算缺项，进入生成"""
    from xiao_wen import memory as ms

    ms.add_or_update_preference("常驻城市", "上海", True)
    plan_out = ItineraryPlan(summary="上海→北京", days=[], reasons=[])
    _stub_models(monkeypatch, _req(from_city="待定"), plan_out=plan_out)
    r = _it.plan("去北京开会")
    assert isinstance(r, _it.PlanResult)
    assert r.plan.summary == "上海→北京"


def test_plan_generates_and_writes_back(monkeypatch):
    """生成成功 → 写回长期记忆（历史行程可读）"""
    from xiao_wen import memory as ms

    plan_out = ItineraryPlan(summary="出差计划", days=[], reasons=[])
    _stub_models(monkeypatch, _req(), plan_out=plan_out)
    r = _it.plan("安排行程")
    assert isinstance(r, _it.PlanResult)
    its = ms.get_itineraries()
    assert len(its) == 1
    assert its[0]["to_city"] == "北京"
    assert its[0]["summary"] == "出差计划"


def test_needs_info_text_lists_missing():
    text = _it.needs_info_text(_it.NeedsInfo(missing=["出发日期", "出差天数"]))
    assert "出发日期" in text and "出差天数" in text
    assert "请补充" in text


# ---------------- 行程“实感”数据层：城市分级 + 车次票价表 + 确定性预算 ----------------


def test_city_tier_matches_policy():
    """城市分级与差旅政策知识库一致：一线 500 / 二线 400 / 三线 300"""
    assert _it.city_tier("北京") == "一线"
    assert _it.city_tier("杭州") == "二线"
    assert _it.city_tier("兰州") == "三线"


def test_train_table_lookup_both_directions():
    """车次表：正向可查；反向同价；未收录线路返回 None"""
    info = _it.train_info("北京", "杭州")
    assert info is not None and info[0] == "G31" and info[4] == 553
    assert _it.train_info("杭州", "北京") is not None  # 反向同线路
    assert _it.train_info("北京", "拉萨") is None


def test_estimate_budget_deterministic():
    """预算估算完全确定（无 LLM）：车次真实票价 + 城市分级住宿 + 餐饮标准"""
    req = _req(to_city="杭州", from_city="北京", duration_days=3)
    b = _it.estimate_budget(req)
    # 杭州=二线 400 元/晚 × 2 晚；G31 往返 553×2；餐饮 200×3
    assert b["tier"] == "二线"
    assert b["hotel_per_night"] == 400 and b["hotel_cost"] == 800
    assert b["transport_cost"] == 1106
    assert b["meal_cost"] == 600
    assert b["total"] == 1106 + 800 + 600


def test_format_budget_readable():
    """预算块含真实数字锚点（车次/票价/标准价/合计），标注参考价"""
    req = _req(to_city="杭州", from_city="北京", duration_days=3)
    text = _it.format_budget(req)
    assert "G31" in text and "553" in text
    assert "400 元/晚 × 2 晚" in text and "≈ 800 元" in text
    assert "参考价" in text and "合计" in text


def test_missing_treats_garbage_city_as_missing(monkeypatch):
    """提取器被 LLM 填了垃圾城市值（如「出差」）时仍应视为缺项——不能编造无目的地行程"""
    assert "目的城市" in _it._missing(_req(to_city="出差"))
    assert "出发城市" in _it._missing(_req(from_city="出差"))
    assert _it._missing(_req(to_city="杭州", from_city="上海")) == []


# ---------------- from_city 哨兵归一化（无→北京 一致性，ticket 04） ----------------


def test_missing_detects_wu_variant():
    """「无」与「待定/未知/出差」同族：缺项检查必须报缺（此前会漏）"""
    assert "目的城市" in _it._missing(_req(to_city="无"))
    assert "出发城市" in _it._missing(_req(from_city="无"))


def test_plan_normalizes_wu_with_home_city(monkeypatch):
    """提取输出 from_city=无 + 有常驻城市 → 归一化→补全→正常生成（不再漏常驻补全）"""
    from xiao_wen import memory as ms

    ms.add_or_update_preference("常驻城市", "上海", True)
    plan_out = ItineraryPlan(summary="上海→北京", days=[], reasons=[])
    _stub_models(monkeypatch, _req(from_city="无"), plan_out=plan_out)
    r = _it.plan("去北京开会")
    assert isinstance(r, _it.PlanResult)
    assert r.request is not None
    assert r.request.from_city == "上海", f"常驻城市应补全，实际 {r.request.from_city}"
    assert r.plan.summary == "上海→北京"


def test_plan_wu_without_home_city_needs_info(monkeypatch):
    """提取输出 from_city=无 且无常驻城市 → 缺项短路（此前会静默进生成→无→北京幻觉）"""
    called = {"plan": False}

    def boom():
        called["plan"] = True
        raise AssertionError("缺项短路：不应调用生成")

    _stub_models(monkeypatch, _req(from_city="无"))
    monkeypatch.setattr(_it, "_plan_model", boom)
    r = _it.plan("去北京开会")
    assert isinstance(r, _it.NeedsInfo)
    assert r.missing == ["出发城市"]
    assert called["plan"] is False


def test_plan_wu_to_city_needs_info(monkeypatch):
    """to_city=无 同样归一化 → 缺项短路（对称处理）"""
    _stub_models(monkeypatch, _req(to_city="无"))
    r = _it.plan("帮我规划出差")
    assert isinstance(r, _it.NeedsInfo)
    assert r.missing == ["目的城市"]


# ---------------- 多轮要素延续：recent 传入提取（E2E-07 暴露的真 bug） ----------------


def test_plan_passes_recent_to_extraction(monkeypatch):
    """补齐轮只补缺项、不重复说过的地方 → recent 必须进提取 payload（此前只给本轮输入）"""
    seen = {}

    class _Capture(_FakeChain):
        def invoke(self, payload):
            seen.update(payload)
            return _req()

    monkeypatch.setattr(_it, "_extract_model", lambda: _Capture(_req()))
    plan_out = ItineraryPlan(summary="杭州出差", days=[], reasons=[])
    monkeypatch.setattr(_it, "_plan_model", lambda: _FakeChain(plan_out))
    _it.plan("10月8日从上海出发，待2天", recent="user: 帮我规划去杭州出差的行程")
    assert "杭州" in seen["recent"], "提取应能看到上文里的目的城市"
    assert seen["recent"] != "无"


def test_plan_recent_defaults_to_wu(monkeypatch):
    """无 recent（新会话首轮）→ 提取收到「无」，不塞入任何伪造上下文"""
    seen = {}

    class _Capture(_FakeChain):
        def invoke(self, payload):
            seen.update(payload)
            return _req()

    monkeypatch.setattr(_it, "_extract_model", lambda: _Capture(_req()))
    plan_out = ItineraryPlan(summary="出差", days=[], reasons=[])
    monkeypatch.setattr(_it, "_plan_model", lambda: _FakeChain(plan_out))
    _it.plan("帮我规划去杭州出差")
    assert seen["recent"] == "无"
