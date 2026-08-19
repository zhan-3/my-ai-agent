"""行程规划纯逻辑测试：必填要素缺失检查 + 结果可读性格式 + 管线编排（无需 LLM）

管线（ADR-0003）收口于 xiao_wen.trip_planner：提取 → 常驻城市补全 → 缺项检查 → 生成 → 写回。
"""

import types
from typing import Any

import xiao_wen.memory
from xiao_wen import trip_planner as _it
from xiao_wen.agents import itinerary_agent

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


def test_format_plan_overall_structure_not_daily():
    """整体结构：去程/住宿/返程 + 每日要点，不再逐日切块【】。"""
    plan = ItineraryPlan(
        summary="10月8日从上海赴北京开会3天",
        days=[
            _it.DayPlan(
                date="2026-10-08",
                transport="高铁 G2 次",
                hotel="全季酒店",
                activities=["抵达后入住酒店"],
                notes="带好身份证",
            ),
            _it.DayPlan(date="2026-10-09", transport="", hotel="", activities=["拜访客户"], notes=""),
            _it.DayPlan(
                date="2026-10-10", transport="高铁 G3 次", hotel="无（当晚返程）", activities=["返程"], notes=""
            ),
        ],
        reasons=["按差旅标准选择住宿"],
    )
    text = _it.format_plan(plan)
    assert "🚄 去程：高铁 G2 次" in text
    assert "🏨 住宿：全季酒店" in text
    assert "🚄 返程：高铁 G3 次" in text
    assert "📌 行程安排" in text
    assert "2026-10-09 拜访客户" in text
    assert "【" not in text  # 不再逐日切块
    assert "无（当晚返程）" not in text  # 返程日住宿不单独成行


def test_format_plan_strips_transport_prefix():
    """LLM 可能误加「去程：/返程：」前缀，format_plan 防御性去重。"""
    plan = ItineraryPlan(
        summary="x",
        days=[
            _it.DayPlan(
                date="2026-10-08",
                transport="去程：航班（具体航班以晓问商旅平台实时查询为准）",
                hotel="酒店",
                activities=[],
                notes="",
            )
        ],
        reasons=[],
    )
    text = _it.format_plan(plan)
    assert "🚄 去程：航班（具体航班以晓问商旅平台实时查询为准）" in text
    assert "去程：去程" not in text


def test_format_plan_long_trip_folds_blank_days():
    """长差（>5 天）折叠空白停留日为一行，结合 purpose。"""
    days = [
        _it.DayPlan(date="2026-10-08", transport="航班", hotel="当地商务酒店", activities=["抵达后入住酒店"], notes=""),
        _it.DayPlan(date="2026-10-09", transport="", hotel="", activities=[], notes=""),
        _it.DayPlan(date="2026-10-10", transport="", hotel="", activities=[], notes=""),
        _it.DayPlan(date="2026-10-11", transport="", hotel="", activities=["拜访客户"], notes=""),
        _it.DayPlan(date="2026-10-12", transport="", hotel="", activities=[], notes=""),
        _it.DayPlan(date="2026-10-13", transport="", hotel="", activities=[], notes=""),
        _it.DayPlan(date="2026-10-14", transport="航班", hotel="无（当晚返程）", activities=["返程"], notes=""),
    ]
    plan = ItineraryPlan(summary="去纽约7天", days=days, reasons=[])
    text = _it.format_plan(plan, purpose="拜访客户")
    assert "2026-10-08 抵达后入住酒店" in text
    assert "2026-10-11 拜访客户" in text
    assert "2026-10-14 返程" in text
    assert "其余 4 天：继续拜访客户" in text
    for blank_date in ("2026-10-09", "2026-10-10", "2026-10-12", "2026-10-13"):
        assert blank_date not in text  # 空白日不逐日列


def test_format_plan_long_trip_no_purpose():
    """长差无 purpose 时折叠行写「无特别安排」。"""
    days = [
        _it.DayPlan(date="2026-10-08", transport="高铁", hotel="酒店", activities=["抵达后入住酒店"], notes=""),
        _it.DayPlan(date="2026-10-09", transport="", hotel="", activities=[], notes=""),
        _it.DayPlan(date="2026-10-10", transport="", hotel="", activities=[], notes=""),
        _it.DayPlan(date="2026-10-11", transport="", hotel="", activities=[], notes=""),
        _it.DayPlan(date="2026-10-12", transport="", hotel="", activities=[], notes=""),
        _it.DayPlan(date="2026-10-13", transport="高铁", hotel="无（当晚返程）", activities=["返程"], notes=""),
    ]
    plan = ItineraryPlan(summary="去北京6天", days=days, reasons=[])
    text = _it.format_plan(plan)
    assert "其余 4 天：无特别安排" in text


def test_format_plan_long_trip_filters_generic_activities():
    """长差中间日 LLM 可能逐日填「出差/工作」泛化活动，代码层过滤并折叠。"""
    days = [
        _it.DayPlan(date="2026-10-08", transport="航班", hotel="当地商务酒店", activities=["抵达后入住酒店"], notes=""),
        _it.DayPlan(date="2026-10-09", transport="", hotel="", activities=["出差"], notes="外出注意安全"),
        _it.DayPlan(date="2026-10-10", transport="", hotel="", activities=["出差"], notes="外出注意安全"),
        _it.DayPlan(date="2026-10-11", transport="", hotel="", activities=["拜访客户"], notes=""),
        _it.DayPlan(date="2026-10-12", transport="", hotel="", activities=["出差"], notes="外出注意安全"),
        _it.DayPlan(date="2026-10-13", transport="", hotel="", activities=["出差"], notes="外出注意安全"),
        _it.DayPlan(date="2026-10-14", transport="航班", hotel="无（当晚返程）", activities=["返程"], notes=""),
    ]
    plan = ItineraryPlan(summary="去纽约7天", days=days, reasons=[])
    text = _it.format_plan(plan, purpose="拜访客户")
    assert "2026-10-11 拜访客户" in text
    assert "其余 4 天：继续拜访客户" in text
    for blank_date in ("2026-10-09", "2026-10-10", "2026-10-12", "2026-10-13"):
        assert blank_date not in text
    assert "外出注意安全" not in text  # 长差中间日通用备注不逐日重复


def test_format_plan_diet_pref_between_hotel_and_itinerary():
    """饮食偏好只在住宿之后提示一次，位于📌行程安排之前。"""
    plan = ItineraryPlan(
        summary="x",
        days=[
            _it.DayPlan(date="2026-10-08", transport="高铁", hotel="全季酒店", activities=["抵达后入住酒店"], notes="")
        ],
        reasons=[],
    )
    text = _it.format_plan(plan, diet_pref="🍽️ 饮食偏好：不吃辣")
    assert text.index("🏨 住宿") < text.index("🍽️ 饮食偏好") < text.index("📌 行程安排")
    assert "用餐：" not in text  # 不逐日写用餐


def test_diet_pref_line_extracts_dining_pref(monkeypatch):
    """饮食偏好从长期偏好/本轮陈述提取，去重；无餐饮偏好返回 None。"""
    monkeypatch.setattr(
        _it,
        "get_preferences",
        lambda session_id=None: [
            {"category": "住宿", "content": "喜欢安静"},
            {"category": "餐饮", "content": "不吃辣"},
        ],
    )
    assert _it._diet_pref_line("u") == "🍽️ 饮食偏好：不吃辣"
    monkeypatch.setattr(_it, "get_preferences", lambda session_id=None: [{"category": "住宿", "content": "喜欢安静"}])
    assert _it._diet_pref_line("u") is None
    # 本轮陈述偏好（turn_prefs）也提取，且与历史去重
    monkeypatch.setattr(_it, "get_preferences", lambda session_id=None: [{"category": "餐饮", "content": "不吃辣"}])
    assert _it._diet_pref_line("u", turn_prefs="餐饮:不吃辣；住宿:喜欢安静") == "🍽️ 饮食偏好：不吃辣"


def test_cut_section_stops_at_next_numbered_section():
    """极端天气节截取：只到「3. 疫情或传染病」之前，不混入后续小节。"""
    text = (
        "台风、暴雨等极端天气\n\n处理步骤：\n"
        "a) 提前关注天气预报\n"
        "b) 如已知有极端天气，考虑延期或取消出差\n"
        "3. 疫情或传染病\n\n处理步骤：\n"
        "a) 关注目的地疫情信息"
    )
    cut = _it._cut_section(text)
    assert "台风、暴雨等极端天气" in cut
    assert "考虑延期或取消出差" in cut
    assert "疫情或传染病" not in cut
    assert "关注目的地疫情信息" not in cut


def test_cut_section_stops_at_next_section_space_separated():
    """真实 chunk：换行已合并为空格，编号标题用空白边界分隔（不依赖 \n）。"""
    text = (
        "台风、暴雨等极端天气  处理步骤： a) 提前关注天气预报 "
        "b) 考虑延期或取消出差  3. 疫情或传染病  处理步骤： a) 关注目的地疫情信息"
    )
    cut = _it._cut_section(text)
    assert "台风、暴雨等极端天气" in cut
    assert "考虑延期或取消出差" in cut
    assert "疫情或传染病" not in cut
    assert "关注目的地疫情信息" not in cut


def test_cut_section_no_next_section_keeps_all():
    assert _it._cut_section("台风、暴雨等极端天气\n处理步骤：a) 待在室内") == (
        "台风、暴雨等极端天气\n处理步骤：a) 待在室内"
    )


def test_mixed_gender_detection():
    assert _it._mixed_gender("改成一男一女")
    assert _it._mixed_gender("男女各一人")
    assert _it._mixed_gender("2男1女")
    assert _it._mixed_gender("一男两女")
    assert _it._mixed_gender("3男2女")
    assert not _it._mixed_gender("两人同行")
    assert not _it._mixed_gender("3人")
    assert not _it._mixed_gender("")


def test_format_emergency_breaks_glued_lines():
    """chunk 粘连成单行的应急文本重新排成分条列表。"""
    glued = (
        "台风、暴雨等极端天气  处理步骤： a) 提前关注天气预报 "
        "b) 如已在地： - 待在室内 - 关注预警 d) 如交通受影响： - 及时改签"
    )
    out = _it._format_emergency(glued)
    assert "处理步骤：\na) 提前关注天气预报" in out
    assert "\nb) 如已在地：" in out
    assert "\n  - 待在室内" in out
    assert "\nd) 如交通受影响：" in out
    assert "\n  - 及时改签" in out


# ---------------- 编排：plan()（模型用桩注入） ----------------


class _FakeChain:
    def __init__(self, out):
        self._out = out
        self.calls: list[dict] = []

    def invoke(self, payload):
        self.calls.append(payload)
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


def test_looks_like_city_name_pure_function():
    """纯城市名启发式：只认 2-4 字城市名（可带「市」）；数字/时间/回复词/方向短语一律拒绝"""
    assert _it._looks_like_city_name("临沂") == "临沂"
    assert _it._looks_like_city_name("北京市") == "北京"
    assert _it._looks_like_city_name("上海") == "上海"
    for bad in ["4天", "明天", "好的", "临沂出发", "从上海", "10月8日", "算了", "嗯"]:
        assert _it._looks_like_city_name(bad) is None, f"{bad!r} 不应被判为城市名"


def test_plan_city_name_fallback_when_extract_stutters(monkeypatch):
    """确定性兜底：提取 LLM 对「追问后回纯城市名」不稳（实测同输入多次 from=待定）
    → 目的城市已知 + 本轮是纯城市名 → 规则直接补出发城市，不再追问"""
    plan_out = ItineraryPlan(summary="临沂→北京", days=[], reasons=[])
    _stub_models(monkeypatch, _req(from_city="待定"), plan_out=plan_out)
    r = _it.plan("临沂", recent="用户: 帮我规划去北京的行程\n助手: 请补充出发城市")
    assert isinstance(r, _it.PlanResult), f"纯城市名应被规则补全为出发城市，实际：{r}"
    assert r.request and r.request.from_city == "临沂"

    # 反向：出发城市已知 + 纯城市名 → 补目的城市
    _stub_models(monkeypatch, _req(to_city="待定"), plan_out=ItineraryPlan(summary="上海→杭州", days=[], reasons=[]))
    r2 = _it.plan("杭州", recent="用户: 我从上海出发\n助手: 请补充目的城市")
    assert isinstance(r2, _it.PlanResult)
    assert r2.request and r2.request.to_city == "杭州"

    # 非纯城市名（回复词）→ 不兜底，走缺项追问
    _stub_models(monkeypatch, _req(from_city="待定"))
    r3 = _it.plan("好的", recent="用户: 去北京\n助手: 请补充出发城市")
    assert isinstance(r3, _it.NeedsInfo)
    assert "出发城市" in r3.missing


def test_plan_injects_upstream_policy_and_history(monkeypatch):
    """collect-then-compose：行程生成必须收到上游上下文（政策/历史参考）；
    未传 upstream（默认）→ 槽位为「无」，行为向后兼容"""
    plan_out = ItineraryPlan(summary="出差计划", days=[], reasons=[])
    extract = _FakeChain(_req())
    plan_chain = _FakeChain(plan_out)
    monkeypatch.setattr(_it, "_extract_model", lambda: extract)
    monkeypatch.setattr(_it, "_plan_model", lambda: plan_chain)

    r = _it.plan(
        "去北京开会",
        upstream={"policy": "一线城市住宿不超过500元/晚", "history_ref": "上次住全季（前门店）"},
    )
    assert isinstance(r, _it.PlanResult)
    payload = plan_chain.calls[-1]
    assert "一线城市住宿不超过500元/晚" in payload["policy"]
    assert "上次住全季（前门店）" in payload["history_ref"]

    # 不传 upstream → 明确禁止无证据政策结论，不崩
    plan_chain2 = _FakeChain(plan_out)
    monkeypatch.setattr(_it, "_plan_model", lambda: plan_chain2)
    _it.plan("去北京开会")
    payload2 = plan_chain2.calls[-1]
    assert "不得引用或推断政策" in payload2["policy"]
    assert payload2["history_ref"] == "无"


def test_weather_window_days():
    """天气窗口：未来 0~6 天在 7 天预报窗口内，第 7 天起超窗，模糊日期返回 None。"""
    from datetime import date as _date
    from datetime import timedelta

    today = _date.today()
    assert _it._weather_window_days((today + timedelta(days=3)).isoformat()) == 3
    assert _it._weather_window_days((today + timedelta(days=6)).isoformat()) == 6
    assert _it._weather_window_days((today + timedelta(days=7)).isoformat()) == 7  # 超窗
    assert _it._weather_window_days("下周") is None


def test_weather_unavailable_is_not_presented_as_weather(monkeypatch):
    assert not _it._weather_is_usable("查询天气失败（服务可能不稳定，请稍后再试）：ValueError")
    assert not _it._weather_is_usable("仅支持未来 7 天预报")
    assert _it._weather_is_usable("北京 2026-10-08 天气：晴，最高 25°C")


def test_weather_attention_flags_severe_conditions():
    assert _it._weather_needs_attention("北京 2026-10-08 天气：雷暴，最高 25°C / 最低 15°C，降水概率 40%")
    assert _it._weather_needs_attention("上海 2026-10-08 天气：多云，最高 25°C / 最低 15°C，降水概率 60%")
    assert not _it._weather_needs_attention("杭州 2026-10-08 天气：晴，最高 25°C / 最低 15°C，降水概率 10%")


def test_collect_upstream_gathers_and_degrades(monkeypatch):
    """collect-then-compose 收集阶段：知识检索 + 历史参考 + 本轮偏好；任一上游异常 → 降级为空，不阻塞"""
    from xiao_wen import memory as ms
    from xiao_wen import rag
    from xiao_wen.agents import itinerary_agent as ia
    from xiao_wen.agents import preference_agent as pa

    # 本轮偏好提取：默认空（无偏好陈述）——避免测试真实调用 LLM
    monkeypatch.setattr(pa, "_invoke_pref_model", lambda _: pa.PreferenceList(records=[]))

    # 正常收集：政策命中 2 段 + 历史最近 2 条
    monkeypatch.setattr(
        rag, "load_chunks", lambda: [("01_travel_standards", "政策段A"), ("01_travel_standards", "政策段B")]
    )
    monkeypatch.setattr(rag, "build_index", lambda chunks: object())
    monkeypatch.setattr(
        rag,
        "_search_with_metadata",
        lambda q, col, k=5: [
            (0.9, {"source": "01_travel_standards"}, "政策段A"),
            (0.8, {"source": "01_travel_standards"}, "政策段B"),
        ],
    )
    monkeypatch.setattr(
        ms,
        "get_itineraries",
        lambda *, session_id="default": [
            {"start_date": "2026-05-01", "from_city": "上海", "to_city": "北京", "duration_days": 4, "summary": "开会"},
            {"start_date": "2026-06-01", "from_city": "济南", "to_city": "湖北", "duration_days": 3, "summary": "拜访"},
            {"start_date": "2026-07-01", "from_city": "临沂", "to_city": "北京", "duration_days": 2, "summary": "培训"},
        ],
    )
    up = ia.collect_upstream("去北京出差住哪", "u1")
    assert "政策段A" in up["policy"] and "政策段B" in up["policy"]
    assert "临沂→北京" in up["history_ref"] and "2026-06-01" in up["history_ref"]  # 取最近 2 条
    assert "2026-05-01" not in up["history_ref"]
    assert up["prefs_turn"] == ""

    # 降级：rag 抛异常 → policy 空；记忆后端抛异常 → history_ref 空；偏好提取抛异常 → prefs_turn 空
    def boom(*a, **k):
        raise RuntimeError("索引不可用")

    monkeypatch.setattr(rag, "load_chunks", boom)
    monkeypatch.setattr(ms, "get_itineraries", boom)
    monkeypatch.setattr(pa, "_invoke_pref_model", boom)
    up2 = ia.collect_upstream("去北京出差住哪", "u1")
    assert up2["policy"] == ""
    assert up2["policy_context"].status == "unavailable"
    assert up2["policy_evidence_ids"] == ()
    assert up2["history_ref"] == ""
    assert up2["prefs_turn"] == ""


def test_trip_policy_unavailable_is_explicit_and_skips_policy_budget(monkeypatch):
    from xiao_wen import rag

    request = _req(start_date="待定")
    plan = ItineraryPlan(summary="上海到北京出差", days=[], reasons=["按用户偏好选择住宿"])
    monkeypatch.setattr(_it, "plan", lambda *args, **kwargs: _it.PlanResult(plan=plan, request=request))
    monkeypatch.setattr(
        _it, "format_budget", lambda req, facts=(): (_ for _ in ()).throw(AssertionError("不应生成政策预算"))
    )
    unavailable = rag.PolicyContext(
        query="政策",
        evidence=(),
        status="unavailable",
        failure=rag.PolicyFailure("index_unavailable", retryable=True),
    )

    outcome = _it.handle("去北京出差", upstream={"policy_context": unavailable})

    assert "政策服务暂时不可用" in outcome.answer
    assert "未引用住宿标准、报销额度或审批时限" in outcome.answer
    assert "费用估算" not in outcome.answer


def test_collect_upstream_uses_recent_city_for_guidance(monkeypatch):
    from xiao_wen import memory as ms
    from xiao_wen import rag
    from xiao_wen.agents import itinerary_agent as ia
    from xiao_wen.agents import preference_agent as pa

    monkeypatch.setattr(
        rag, "retrieve_trip_policy", lambda _: rag.PolicyContext(query="", evidence=(), status="not_found")
    )
    monkeypatch.setattr(rag, "search_texts", lambda _: [])
    monkeypatch.setattr(
        rag,
        "retrieve_guidance",
        lambda city: (rag.Evidence("city", city + "城市提示", "", 0.9),),
    )
    monkeypatch.setattr(ms, "get_itineraries", lambda *, session_id="default": [])
    monkeypatch.setattr(pa, "_invoke_pref_model", lambda _: pa.PreferenceList(records=[]))

    up = ia.collect_upstream("4天", "u1", recent="助手：请补充目的城市\n用户：北京")
    assert "北京城市提示" in up["guidance"]
    assert up["guidance_sources"] == ("北京城市提示",)


def test_collect_upstream_extracts_turn_prefs(monkeypatch):
    """本轮含偏好陈述 → 结构化提取进 prefs_turn（不写库，只供生成上下文）"""
    from xiao_wen import memory as ms
    from xiao_wen import rag
    from xiao_wen.agents import itinerary_agent as ia
    from xiao_wen.agents import preference_agent as pa

    monkeypatch.setattr(
        rag, "retrieve_trip_policy", lambda _: rag.PolicyContext(query="", evidence=(), status="not_found")
    )
    monkeypatch.setattr(rag, "retrieve_guidance", lambda city: ())
    monkeypatch.setattr(ms, "get_itineraries", lambda *, session_id="default": [])
    monkeypatch.setattr(
        pa,
        "_invoke_pref_model",
        lambda _: pa.PreferenceList(
            records=[
                pa.PreferenceRecord(category="住宿", content="喜欢住全季", is_update=False),
                pa.PreferenceRecord(category="常驻城市", content="上海", is_update=True),
            ]
        ),
    )
    up = ia.collect_upstream("帮我安排行程，喜欢住全季", "u1")
    assert up["prefs_turn"] == "住宿:喜欢住全季；常驻城市:上海"


def test_plan_home_city_completes_before_missing_check(monkeypatch):
    """常驻城市补全先于缺项检查：缺出发城市但有常驻城市 → 不算缺项，进入生成"""
    from xiao_wen import memory as ms

    ms.add_or_update_preference("常驻城市", "上海", True)
    plan_out = ItineraryPlan(summary="上海→北京", days=[], reasons=[])
    _stub_models(monkeypatch, _req(from_city="待定"), plan_out=plan_out)
    r = _it.plan("去北京开会")
    assert isinstance(r, _it.PlanResult)
    assert r.plan.summary == "上海→北京"


def test_detect_home_city_pure_function():
    assert _it._detect_home_city("从常住地临沂") == "临沂"
    assert _it._detect_home_city("从常住地临沂去北京开会") == "临沂"
    assert _it._detect_home_city("我常住上海") == "上海"
    assert _it._detect_home_city("家在杭州") == "杭州"
    assert _it._detect_home_city("我目前住在深圳") == "深圳"
    assert _it._detect_home_city("帮我规划去北京的行程") == ""
    assert _it._detect_home_city("好的") == ""
    assert _it._detect_home_city("我明天去上海") == ""


def test_plan_declares_home_city_writes_preference_deferred(monkeypatch):
    """「从常住地临沂」→ 常驻城市偏好进入延迟写清单，不直接落库"""
    from xiao_wen import memory as ms

    plan_out = ItineraryPlan(summary="临沂→北京", days=[], reasons=[])
    _stub_models(monkeypatch, _req(from_city="临沂"), plan_out=plan_out)
    r = _it.plan("从常住地临沂去北京开会", defer_write=True)
    assert isinstance(r, _it.PlanResult)
    assert r.home_city == "临沂"
    assert {"type": "preference", "category": "常驻城市", "content": "临沂", "is_update": True} in r.memory_writes
    assert ms.get_preferences() == []  # 延迟写：库中暂未出现


def test_plan_declares_home_city_writes_direct(monkeypatch):
    """非延迟路径：常驻城市偏好直接写入"""
    from xiao_wen import memory as ms

    plan_out = ItineraryPlan(summary="临沂→北京", days=[], reasons=[])
    _stub_models(monkeypatch, _req(from_city="临沂"), plan_out=plan_out)
    r = _it.plan("从常住地临沂去北京开会")
    assert isinstance(r, _it.PlanResult)
    assert r.home_city == "临沂"
    prefs = ms.get_preferences()
    assert any(p["category"] == "常驻城市" and p["content"] == "临沂" for p in prefs)


def test_plan_does_not_redeclare_existing_home_city(monkeypatch):
    """已有常驻城市且本轮声明相同 → 不重复写、不声明"""
    from xiao_wen import memory as ms

    ms.add_or_update_preference("常驻城市", "临沂", True)
    plan_out = ItineraryPlan(summary="临沂→北京", days=[], reasons=[])
    _stub_models(monkeypatch, _req(from_city="临沂"), plan_out=plan_out)
    r = _it.plan("从常住地临沂去北京开会", defer_write=True)
    assert isinstance(r, _it.PlanResult)
    assert r.home_city == ""
    assert all(w.get("type") != "preference" for w in r.memory_writes)


def test_plan_does_not_write_back_when_runtime_validation_fails(monkeypatch):
    """日期与天数不一致时阻断写回，避免把未经证明的候选行程存进历史。"""
    from xiao_wen import memory as ms

    bad_plan = ItineraryPlan(
        summary="错误行程",
        days=[
            _it.DayPlan(
                date="2026-10-08",
                transport="高铁",
                hotel="酒店",
                activities=["开会"],
                notes="",
            )
        ],
        reasons=[],
    )
    _stub_models(monkeypatch, _req(duration_days=4), plan_out=bad_plan)
    r = _it.plan("安排行程")
    assert isinstance(r, _it.ValidationFailure)
    assert any("天" in issue for issue in r.issues)
    assert ms.get_itineraries() == []


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


def test_plan_derives_duration_from_return_date(monkeypatch):
    """用户给了明确返程日期但没说天数 → 用日期差推算 duration_days（含首尾）"""
    req = _req(duration_days=0, return_date="2026-10-12")  # 默认 10-08 出发
    plan_out = ItineraryPlan(summary="五天行程", days=[], reasons=[])
    _stub_models(monkeypatch, req, plan_out=plan_out)
    r = _it.plan("10月8日去北京，12日回")
    assert isinstance(r, _it.PlanResult)
    assert r.request is not None
    assert r.request.duration_days == 5  # 10-08 → 10-12 含首尾 5 天


def test_plan_normalizes_people_count(monkeypatch):
    """人数为字符串「待定」或 0 → 归一化成 1；数字字符串「3」→ 3"""
    plan_out = ItineraryPlan(summary="出行", days=[], reasons=[])

    _stub_models(monkeypatch, _req(people_count="待定"), plan_out=plan_out)
    r1 = _it.plan("安排行程")
    assert isinstance(r1, _it.PlanResult)
    assert r1.request is not None
    assert r1.request.people_count == 1

    _stub_models(monkeypatch, _req(people_count="3"), plan_out=plan_out)
    r2 = _it.plan("安排行程")
    assert isinstance(r2, _it.PlanResult)
    assert r2.request is not None
    assert r2.request.people_count == 3

    _stub_models(monkeypatch, _req(people_count=0), plan_out=plan_out)
    r3 = _it.plan("安排行程")
    assert isinstance(r3, _it.PlanResult)
    assert r3.request is not None
    assert r3.request.people_count == 1


def test_plan_injects_turn_prefs_into_generation(monkeypatch):
    """上游含本轮偏好 → plan 生成时并入 prefs（消除多意图写读竞态）"""
    plan_out = ItineraryPlan(summary="行程", days=[], reasons=[])
    chain = _FakeChain(plan_out)
    monkeypatch.setattr(_it, "_extract_model", lambda: _FakeChain(_req()))
    monkeypatch.setattr(_it, "_plan_model", lambda: chain)
    r = _it.plan("安排行程", upstream={"policy": "", "history_ref": "", "prefs_turn": "住宿:喜欢住全季"})
    assert isinstance(r, _it.PlanResult)
    assert "本轮陈述偏好：住宿:喜欢住全季" in chain.calls[0]["prefs"]


def test_needs_info_text_lists_missing():
    text = _it.needs_info_text(_it.NeedsInfo(missing=["出发日期", "出差天数"]))
    assert "出发日期" in text and "出差天数" in text
    assert "请补充" in text


# ---------------- 政策标准预算（读 RAG facts） ----------------


def _policy_facts():
    from xiao_wen.rag import PolicyFact

    return (
        PolicyFact("hotel_rate", 500, "元/晚", {"city_tier": "一线"}, ()),
        PolicyFact("hotel_rate", 400, "元/晚", {"city_tier": "二线"}, ()),
        PolicyFact("hotel_rate", 300, "元/晚", {"city_tier": "三线"}, ()),
        PolicyFact("meal_rate", 100, "元/餐", {}, ()),
    )


def test_city_tier_classifies():
    assert _it._city_tier("北京") == "一线"
    assert _it._city_tier("杭州") == "二线"
    assert _it._city_tier("临沂") == "三线"


def test_estimate_budget_reads_policy_facts():
    """预算金额读自 RAG 政策事实（酒店/餐饮标准），不依赖本地预算档常量。"""
    req = _req(to_city="杭州", from_city="北京", duration_days=3)
    b = _it.estimate_budget(req, _policy_facts())
    assert "transport_cost" not in b
    assert b["hotel_rate"] == 400 and b["hotel_cost"] == 800  # 二线 400 × 2 晚
    assert b["meal_cost"] == 600  # 100/餐 × 2 餐 × 3 天
    assert b["total"] == 800 + 600


def test_format_budget_readable():
    """预算块明确政策标准上限，并拒绝提供交通金额。"""
    req = _req(to_city="杭州", from_city="北京", duration_days=3)
    text = _it.format_budget(req, _policy_facts())
    assert "晓问商旅平台" in text and "交通：不提供金额" in text
    assert "400 元/晚 × 2 晚" in text and "≈ 800 元" in text
    assert "按公司差旅标准上限" in text and "不含交通" in text


def test_estimate_budget_day_trip_no_hotel():
    """一日往返：不住宿（0 晚），住宿费为 0，只算当日餐饮。"""
    req = _req(to_city="杭州", from_city="北京", duration_days=1)
    b = _it.estimate_budget(req, _policy_facts())
    assert b["nights"] == 0
    assert b["hotel_cost"] == 0
    assert b["hotel_rate"] == 400
    assert b["total"] == b["meal_cost"]


def test_format_budget_day_trip_no_hotel_line():
    """一日往返：预算块不出现「× 0 晚」，明示无住宿。"""
    req = _req(to_city="杭州", from_city="北京", duration_days=1)
    text = _it.format_budget(req, _policy_facts())
    assert "0 晚" not in text
    assert "无需住宿" in text


def test_estimate_budget_uses_city_tier():
    """住宿标准按目的地城市分级：一线 500 / 二线 400 / 三线 300。"""
    assert _it.estimate_budget(_req(to_city="北京"), _policy_facts())["hotel_rate"] == 500
    assert _it.estimate_budget(_req(to_city="杭州"), _policy_facts())["hotel_rate"] == 400
    assert _it.estimate_budget(_req(to_city="临沂"), _policy_facts())["hotel_rate"] == 300


def test_estimate_budget_multiplies_by_people():
    """多人出行：房数向上取整，住宿和餐饮按人数计算，交通仍不报数。"""
    req = _req(to_city="杭州", from_city="北京", duration_days=3, people_count=3)
    b = _it.estimate_budget(req, _policy_facts())
    assert b["people"] == 3
    assert b["rooms"] == 2  # 3 人 → 2 间双人标间
    assert "transport_cost" not in b
    assert b["hotel_cost"] == 400 * 2 * 2
    assert b["meal_cost"] == 100 * 2 * 3 * 3
    assert b["total"] == b["hotel_cost"] + b["meal_cost"]


def test_format_budget_shows_people_when_multi():
    """多人：预算块明示人数与房数。"""
    req = _req(to_city="杭州", from_city="北京", duration_days=3, people_count=3)
    text = _it.format_budget(req, _policy_facts())
    assert "× 3 人" in text
    assert "× 2 间" in text


def test_format_budget_without_facts_hides_amount():
    """无政策事实时不显示金额，引导以差旅标准/财务口径为准。"""
    req = _req(to_city="杭州", from_city="北京", duration_days=3)
    text = _it.format_budget(req, ())
    assert "元/晚" not in text
    assert "政策服务未提供有效标准数字" in text


def test_estimate_budget_overseas_no_local_rates():
    """境外：本地人民币标准不适用，金额一律不估算（防止海外城市误套三线 300 元）。"""
    req = _req(to_city="纽约", from_city="北京", duration_days=3)
    b = _it.estimate_budget(req, _policy_facts(), overseas=True)
    assert b["overseas"] is True
    assert b["hotel_rate"] is None and b["hotel_cost"] is None
    assert b["meal_cost"] is None and b["total"] is None
    assert b["city_tier"] is None


def test_format_budget_overseas_no_cny_amount():
    """境外预算块：不显示人民币金额，明示以当地差旅政策为准。"""
    req = _req(to_city="纽约", from_city="北京", duration_days=3)
    text = _it.format_budget(req, _policy_facts(), overseas=True)
    assert "元/晚" not in text and "元/餐" not in text
    assert "海外出行" in text and "当地差旅政策" in text
    assert "交通：不提供金额" in text  # 交通行不变


def test_format_budget_unknown_overseas_hides_amount():
    """境外无法判定（geocoding 失败）：不显示金额、不误套人民币标准。"""
    req = _req(to_city="未知名城", from_city="北京", duration_days=3)
    text = _it.format_budget(req, _policy_facts(), overseas=None)
    assert "元/晚" not in text and "元/餐" not in text
    assert "无法确定当地差旅标准" in text


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


# ---------------- 展示补齐重点要素：人数 ----------------


def test_handle_shows_people_count(monkeypatch):
    """行程展示补齐重点要素：人数（>1 时）"""
    from xiao_wen import web

    request = _req(from_city="临沂", to_city="北京", people_count=3)
    plan = ItineraryPlan(summary="临沂去北京开会", days=[], reasons=[])

    monkeypatch.setattr(_it, "plan", lambda *a, **k: _it.PlanResult(plan=plan, request=request))

    class _FakeWeather:
        def invoke(self, payload):
            return "晴，最高 25°C"

    monkeypatch.setattr(web, "get_weather", _FakeWeather())

    outcome = _it.handle("我们3个人从临沂去北京开会4天")
    assert "本次出行 3 人" in outcome.answer
    assert "住宿按 2 间房" in outcome.answer


# ---- 行程子 Agent 薄适配层（itinerary_agent）：城市提示/偏好注入/草稿上下文/trip_id 绑定 ----


def test_extract_city_hints_whitelist_order_and_dedupe():
    """白名单城市：按出现顺序去重。"""
    assert itinerary_agent._extract_city_hints("从北京去上海出差") == ("北京", "上海")
    assert itinerary_agent._extract_city_hints("北京和北京的行程") == ("北京",)


def test_extract_city_hints_non_whitelist_origin_and_home():
    """非白名单出发城市（临沂）与常驻城市声明都能提取。"""
    hints = itinerary_agent._extract_city_hints("从临沂出发去北京开会")
    assert "临沂" in hints and "北京" in hints
    hints2 = itinerary_agent._extract_city_hints("我常住临沂")
    assert "临沂" in hints2


def test_extract_city_hints_skips_location_words_and_limits():
    """排除「从家里出发」这类地点词；最多 3 个城市。"""
    assert itinerary_agent._extract_city_hints("从家里出发去上班") == ()
    many = itinerary_agent._extract_city_hints("北京上海广州深圳四个城市")
    assert len(many) <= 3


def test_extract_destination_hint_prefers_destination_over_home():
    """目的地提取：不把常驻城市误当目的地。"""
    assert itinerary_agent._extract_destination_hint("我常住上海，想去北京开会") == "北京"
    assert itinerary_agent._extract_destination_hint("后天去武汉") == "武汉"


def test_extract_destination_hint_falls_back_to_recent():
    """recent 兜底：本轮没提目的地时从最近对话提取。"""
    assert itinerary_agent._extract_destination_hint("那安排一下", recent="后天去武汉开会2天") == "武汉"


def test_extract_turn_prefs_joins_records(monkeypatch):
    """本轮偏好结构化提取：真实 _extract_turn_prefs 拼 category:content 行。"""
    import xiao_wen.agents.preference_agent as pa
    from xiao_wen.agents.preference_agent import PreferenceList, PreferenceRecord

    monkeypatch.setattr(
        pa,
        "_invoke_pref_model",
        lambda text: PreferenceList(
            records=[
                PreferenceRecord(category="住宿", content="喜欢安静", is_update=False),
                PreferenceRecord(category="餐饮", content="不吃辣", is_update=False),
            ]
        ),
    )
    assert itinerary_agent._extract_turn_prefs("我喜欢安静，不吃辣") == "住宿:喜欢安静；餐饮:不吃辣"


def test_extract_turn_prefs_degrades_on_failure(monkeypatch):
    """偏好提取失败降级为空（不阻塞规划）。"""

    def boom(text):
        raise RuntimeError("llm down")

    import xiao_wen.agents.preference_agent as pa

    monkeypatch.setattr(pa, "_invoke_pref_model", boom)
    assert itinerary_agent._extract_turn_prefs("x") == ""


def test_drafting_context_lists_drafts(monkeypatch):
    """集合式续接：线程内多草稿注入上下文。"""
    drafts = [
        {
            "id": 1,
            "status": "drafting",
            "start_date": "2026-09-01",
            "to_city": "北京",
            "missing": ["出发城市"],
            "resume_context": "",
        },
        {
            "id": 2,
            "status": "drafting",
            "start_date": "2026-09-05",
            "to_city": "广州",
            "missing": [],
            "resume_context": "已收集人数",
        },
    ]
    monkeypatch.setattr(xiao_wen.memory, "get_trips", lambda **kw: drafts)
    ctx = itinerary_agent._drafting_context("u1", {"resume_context": "单条"})
    assert "草稿#1" in ctx and "草稿#2" in ctx
    assert "待补：['出发城市']" in ctx


def test_drafting_context_degrades_to_active(monkeypatch):
    """记忆异常降级为单条活跃任务上下文。"""

    def boom(**kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(xiao_wen.memory, "get_trips", boom)
    ctx = itinerary_agent._drafting_context("u1", {"resume_context": "单条上下文"})
    assert ctx == "单条上下文"


def _fake_handle_out():
    return types.SimpleNamespace(
        answer="好的，已调整。",
        plan=None,
        task_update=None,
        memory_writes=[],
    )


def test_run_binds_trip_id_on_modify_words(monkeypatch):
    """run()：修改词 + 最近行程 → handle 收到 trip_id=最近行程 id。"""
    seen = {}
    monkeypatch.setattr(
        xiao_wen.trip_planner,
        "handle",
        lambda *a, **kw: seen.update(kw) or _fake_handle_out(),
    )
    monkeypatch.setattr(xiao_wen.memory, "get_trips", lambda **kw: [])
    result = itinerary_agent.run(
        {
            "user_input": "把行程改成一男一女",
            "session_id": "c1",
            "user_id": "u1",
            "recent": "最近对话",
            "latest_trip": {"id": 7, "to_city": "北京", "start_date": "2026-09-01"},
            "upstream": {"policy_status": "grounded", "sources": []},
        }
    )
    assert seen.get("trip_id") == 7
    assert result["answer"] == "好的，已调整。"


def test_run_prefers_active_task_trip_id(monkeypatch):
    """run()：活跃任务（drafting 续接）的 trip_id 优先于修改词绑定。"""
    seen = {}
    monkeypatch.setattr(
        xiao_wen.trip_planner,
        "handle",
        lambda *a, **kw: seen.update(kw) or _fake_handle_out(),
    )
    monkeypatch.setattr(xiao_wen.memory, "get_trips", lambda **kw: [])
    itinerary_agent.run(
        {
            "user_input": "补上出发城市：从上海出发",
            "session_id": "c1",
            "user_id": "u1",
            "active_task": {"intent": "行程规划", "trip_id": 3, "missing": ["出发城市"]},
            "upstream": {"policy_status": "grounded", "sources": []},
        }
    )
    assert seen.get("trip_id") == 3


def test_run_new_trip_has_no_trip_id(monkeypatch):
    """run()：全新行程不带 trip_id（走身份去重/新建，不误覆盖历史）。"""
    seen = {}
    monkeypatch.setattr(
        xiao_wen.trip_planner,
        "handle",
        lambda *a, **kw: seen.update(kw) or _fake_handle_out(),
    )
    monkeypatch.setattr(xiao_wen.memory, "get_trips", lambda **kw: [])
    itinerary_agent.run(
        {
            "user_input": "帮我规划10月8日去北京开会4天",
            "session_id": "c1",
            "user_id": "u1",
            "latest_trip": {"id": 7, "to_city": "北京"},
            "upstream": {"policy_status": "grounded", "sources": []},
        }
    )
    assert seen.get("trip_id") is None
