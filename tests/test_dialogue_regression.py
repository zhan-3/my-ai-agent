"""对话细节回归集：把实机测试暴露的对话漏洞固化为真实 LLM 回归用例。

每个用例对应一个曾经"靠人工实机挖掘"出来的漏洞，断言结构化 outcome
（intent / plan / 落库状态 / 无思维链泄漏），不锁定模型措辞。

这些用例跑真实 LLM，不进确定性门禁；每次对话/意图/编排行为变化后按需回归：

    uv run pytest -q -m "integration" tests/test_dialogue_regression.py

维护约定：每修一个"对话细节"漏洞，就在本文件补一条对应用例，形成
「漏洞 → 修复 → 回归」闭环，避免同类问题靠下一次实机测试才暴露。

注意：integration 测试落在干净的测试库，无常驻城市偏好，规划用例必须自包含
（带上出发城市或先声明常驻城市），不要依赖开发库里的账号状态。
"""

from datetime import date, timedelta

import pytest

from xiao_wen import memory
from xiao_wen.session import chat

# 主管最终回答不得泄漏英文思维链文本（历史漏洞：I need to… / Let me…）
_REASONING_LEAK_MARKERS = ("I need to", "Let me", "First,", "Next,")


def _assert_no_reasoning_leak(answer: str) -> None:
    for marker in _REASONING_LEAK_MARKERS:
        assert marker not in answer, f"答案泄漏英文思维链标记: {marker!r}"


def _trips(user_id: str) -> list[dict]:
    """按用户取全部非 cancelled 行程（memory 层 session_id 语义是 user_id）。"""
    return memory.get_trips(session_id=user_id)


@pytest.mark.integration
def test_pure_fact_listing_plans_directly():
    """漏洞：纯要素列举「后天,2人,去武汉,2天」被误判非行程 → 主管编造缺项 + 泄漏思维链。"""
    user_id = "regr-fact-listing"
    chat("我常住临沂", f"{user_id}:t1", user_id=user_id)
    result = chat("后天, 2人, 去武汉, 2天", f"{user_id}:t1", user_id=user_id)
    assert result.intent == "行程规划"
    assert result.plan is not None
    _assert_no_reasoning_leak(result.answer)
    assert any(t["to_city"] == "武汉" for t in _trips(user_id))


@pytest.mark.integration
def test_modify_existing_trip_updates_same_row():
    """漏洞：规划后「改成一男一女」不被子 Agent 接收 → 主管编造回答、不落库。"""
    user_id = "regr-modify"
    thread = f"{user_id}:t1"
    first = chat("后天从临沂去武汉出差两天，2人", thread, user_id=user_id)
    assert first.intent == "行程规划" and first.plan is not None
    assert len(_trips(user_id)) == 1

    modify = chat("改成一男一女", thread, user_id=user_id)
    assert modify.intent == "行程规划"
    assert modify.plan is not None
    _assert_no_reasoning_leak(modify.answer)
    trips = _trips(user_id)
    assert len(trips) == 1, "修改已有行程应更新同一条，不得新建重复档案"
    assert trips[0]["people_count"] == 2
    assert trips[0]["mixed_gender"] is True
    # 异性同行必须分房（本次修复的语义点）
    assert "分房" in modify.answer or "2 间" in modify.answer


@pytest.mark.integration
def test_new_trip_does_not_overwrite_history():
    """漏洞防护：已有行程后说新行程，不得误更新旧行程。"""
    user_id = "regr-new-trip"
    thread = f"{user_id}:t1"
    first = chat("后天从临沂去武汉出差两天，2人", thread, user_id=user_id)
    assert first.intent == "行程规划" and first.plan is not None

    second = chat("下个月从临沂去北京开会3天", thread, user_id=user_id)
    assert second.intent == "行程规划" and second.plan is not None
    assert sorted(t["to_city"] for t in _trips(user_id)) == ["北京", "武汉"]


@pytest.mark.integration
def test_reschedule_updates_latest_trip_date():
    """漏洞防护：「改期到明天」更新最新行程日期，不新建。"""
    user_id = "regr-reschedule"
    thread = f"{user_id}:t1"
    first = chat("后天从临沂去武汉出差两天，2人", thread, user_id=user_id)
    assert first.intent == "行程规划" and first.plan is not None

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    modify = chat("改期到明天", thread, user_id=user_id)
    assert modify.intent == "行程规划" and modify.plan is not None
    trips = _trips(user_id)
    assert len(trips) == 1
    assert trips[0]["start_date"] == tomorrow


@pytest.mark.integration
def test_leisure_requests_are_not_business_plans():
    """漏洞防护：休闲/度假（周末去玩、五一去三亚）归「其他」，不生成企业行程。

    风险：纯要素列举门禁会匹配「去南京…两天」，把「玩」误判成企业行程规划。
    """
    user_id = "regr-leisure"
    thread = f"{user_id}:t1"
    result = chat("周末去南京玩两天", thread, user_id=user_id)
    assert result.intent == "其他"
    assert result.plan is None
    assert _trips(user_id) == []

    result2 = chat("五一去三亚度假5天", thread, user_id=user_id)
    assert result2.intent == "其他"
    assert result2.plan is None
    assert _trips(user_id) == []


@pytest.mark.integration
def test_ticket_booking_defers_to_platform():
    """漏洞防护：订票请求不生成行程、不编造车次，引导商旅平台。"""
    user_id = "regr-ticket"
    result = chat("帮我订明天去北京的高铁票", f"{user_id}:t1", user_id=user_id)
    assert result.plan is None
    assert _trips(user_id) == []
    assert "商旅平台" in result.answer or "travel.xiaowen.com" in result.answer


@pytest.mark.integration
def test_cancel_upcoming_trip_by_dialogue():
    """漏洞：对话层无法取消已确定的行程（upcoming），只能靠前端叉号。"""
    user_id = "regr-cancel-upcoming"
    thread = f"{user_id}:t1"
    first = chat("后天从临沂去武汉出差两天，2人", thread, user_id=user_id)
    assert first.intent == "行程规划" and first.plan is not None
    assert len(_trips(user_id)) == 1

    cancel = chat("把武汉那个行程取消掉", thread, user_id=user_id)
    assert "取消" in cancel.answer
    assert _trips(user_id) == [], "对话取消后 cancelled 行程应被 get_trips 排除"


@pytest.mark.integration
def test_cancel_drafting_by_dialogue():
    """漏洞防护：缺项追问（drafting）中说「算了/不去了」取消行程。"""
    user_id = "regr-cancel-drafting"
    thread = f"{user_id}:t1"
    first = chat("帮我规划去北京的行程", thread, user_id=user_id)
    assert first.intent == "行程规划" and first.plan is None  # 缺项 → drafting

    cancel = chat("算了，不去了", thread, user_id=user_id)
    assert "取消" in cancel.answer
    assert _trips(user_id) == [], "drafting 取消后应转为 cancelled 并从 get_trips 排除"


@pytest.mark.integration
def test_reschedule_to_past_date_is_rejected():
    """漏洞：改期到过去日期会生成过去行程（落库成 completed），应被拒绝并保留原行程。"""
    user_id = "regr-past-date"
    thread = f"{user_id}:t1"
    first = chat("后天从临沂去武汉出差两天，2人", thread, user_id=user_id)
    assert first.intent == "行程规划" and first.plan is not None
    assert len(_trips(user_id)) == 1

    result = chat("改期到上个月", thread, user_id=user_id)
    assert result.plan is None
    trips = _trips(user_id)
    assert len(trips) == 1, "改期到过去日期不得新建/复制行程"
    assert trips[0]["start_date"] >= date.today().isoformat(), "原行程不得被改成过去日期"


@pytest.mark.integration
def test_second_trip_in_same_thread_after_success():
    """漏洞：同一对话里一次完整规划后，再规划新行程触发 agent_limit（前端显示网络错误）。

    根因：门禁在 active_task 存在时把「新行程」当「补全缺项」，既不认补全也不认新行程 → 误拒 →
    主管反复重试到 max_steps。用户实机报告「一次规划后不 new 对话直接再规划出 bug」。
    """
    user_id = "regr-second-trip"
    thread = f"{user_id}:t1"
    chat("我常住临沂", thread, user_id=user_id)
    first = chat("帮我规划10月8日去北京开会4天的行程", thread, user_id=user_id)
    assert first.intent == "行程规划" and first.plan is not None
    assert getattr(first, "failure", None) is None

    second = chat("后天我要去武汉开两天的会", thread, user_id=user_id)
    assert getattr(second, "failure", None) is None, f"第二次规划不得触发失败: {getattr(second, 'failure', None)}"
    assert second.intent == "行程规划" and second.plan is not None
    trips = _trips(user_id)
    assert {t["to_city"] for t in trips} >= {"北京", "武汉"}, "两次规划应分别落库，不互相覆盖"


@pytest.mark.integration
def test_reimbursement_deadline_qa():
    """8 份文档盲区：报销时限（02）问答走知识问答 + 带 RAG 来源，不编造数字。"""
    user_id = "regr-doc-reimb"
    result = chat("出差回来后多久要提交报销申请？", f"{user_id}:t1", user_id=user_id)
    assert result.intent == "知识问答"
    assert "30" in result.answer
    assert result.sources, "报销政策回答必须携带 RAG 来源"


@pytest.mark.integration
def test_booking_lead_time_and_hotline_qa():
    """8 份文档盲区：预订提前量 + 客服热线（03）问答。"""
    user_id = "regr-doc-booking"
    result = chat("国内机票提前多久订最划算？", f"{user_id}:t1", user_id=user_id)
    assert result.intent == "知识问答"
    assert "7" in result.answer or "14" in result.answer
    result2 = chat("客服热线是多少？", f"{user_id}:t1", user_id=user_id)
    assert "400-800-8888" in result2.answer


@pytest.mark.integration
def test_faq_and_platform_qa():
    """8 份文档盲区：审批前置天数（04）+ 平台网址（06）问答。"""
    user_id = "regr-doc-faq"
    result = chat("出差申请要提前多久提交？", f"{user_id}:t1", user_id=user_id)
    assert result.intent == "知识问答"
    assert "3" in result.answer
    result2 = chat("晓问商旅平台的网址是什么？", f"{user_id}:t1", user_id=user_id)
    assert "travel.xiaowen.com" in result2.answer


@pytest.mark.integration
def test_city_tips_qa():
    """8 份文档盲区：城市注意事项（07）问答。"""
    user_id = "regr-doc-city"
    result = chat("北京出差，机场怎么选？", f"{user_id}:t1", user_id=user_id)
    assert result.intent == "知识问答"
    assert any(key in result.answer for key in ("大兴", "首都", "PEK", "PKX"))


@pytest.mark.integration
def test_green_initiative_qa():
    """8 份文档盲区：绿色倡议（08）问答。"""
    user_id = "regr-doc-green"
    result = chat("出差绿色出行有什么建议？", f"{user_id}:t1", user_id=user_id)
    assert result.intent == "知识问答"
    assert "高铁" in result.answer


@pytest.mark.integration
def test_emergency_procedure_qa():
    """8 份文档盲区：应急手册（05）问答。"""
    user_id = "regr-doc-emergency"
    result = chat("出差时航班延误了怎么办？", f"{user_id}:t1", user_id=user_id)
    assert any(key in result.answer for key in ("改签", "延误证明", "航空公司"))


@pytest.mark.integration
def test_travel_standard_approval_qa():
    """8 份文档盲区：差旅标准审批（01）问答。"""
    user_id = "regr-doc-standard"
    result = chat("一般出差谁来审批？", f"{user_id}:t1", user_id=user_id)
    assert "主管" in result.answer


@pytest.mark.integration
def test_return_before_departure_rejected():
    """返程早于出发（10月8日去、10月5日回）不得生成/落库成完整行程。

    目前 plan() 的过去日期拦截只查 start_date；返程早于出发靠 return_date_mismatch
    间接拦截。断言：不生成 plan、不落库 upcoming（drafting 追问允许，但不得有完整行程）。
    """
    user_id = "regr-return-before"
    thread = f"{user_id}:t1"
    chat("我常住临沂", thread, user_id=user_id)
    result = chat("10月8日去北京出差3天，10月5日回", thread, user_id=user_id)
    assert result.plan is None, "返程早于出发不得生成完整行程"
    trips = _trips(user_id)
    assert not any(t["status"] == "upcoming" for t in trips), "返程早于出发不得落库成 upcoming 行程"


@pytest.mark.integration
def test_vague_date_flags_inference():
    """模糊日期（只说了「下周」）→ date_is_vague=true，答案明示按推断日期安排，给用户确认机会。"""
    user_id = "regr-vague-date"
    thread = f"{user_id}:t1"
    chat("我常住临沂", thread, user_id=user_id)
    result = chat("下周从临沂去北京出差3天", thread, user_id=user_id)
    assert result.intent == "行程规划"
    assert result.plan is not None
    assert result.plan.date_is_vague is True
    assert "开始安排" in result.answer or "大致范围" in result.answer


@pytest.mark.integration
def test_mixed_gender_digit_format_splits_rooms():
    """漏洞：`2男1女` 这类数字+性别组合不被 _mixed_gender 识别 → 异性同行被按同性拼房。

    修复后 mixed_gender=true，3 人按 3 间房（每人一间）保守分房。
    """
    user_id = "regr-mixed-digit"
    thread = f"{user_id}:t1"
    result = chat("后天从临沂去武汉出差3天，2男1女", thread, user_id=user_id)
    assert result.intent == "行程规划" and result.plan is not None
    trips = _trips(user_id)
    assert len(trips) == 1
    assert trips[0]["mixed_gender"] is True
    assert trips[0]["people_count"] == 3
    assert "3 间" in result.answer or "分房" in result.answer


@pytest.mark.integration
def test_odd_people_count_split_rooms():
    """奇数人数（3人，无性别信息）→ rooms=(3+1)//2=2 间，不出现分房错误。"""
    user_id = "regr-odd-people"
    thread = f"{user_id}:t1"
    result = chat("后天从临沂去武汉出差3天，3人", thread, user_id=user_id)
    assert result.intent == "行程规划" and result.plan is not None
    trips = _trips(user_id)
    assert len(trips) == 1
    assert trips[0]["people_count"] == 3
    assert trips[0]["mixed_gender"] is False
    assert "2 间" in result.answer


@pytest.mark.integration
def test_cross_account_isolation():
    """双账号隔离：A 的常驻城市/行程，B 完全看不到、不受影响。"""
    user_a = "regr-iso-a"
    user_b = "regr-iso-b"
    chat("我常住临沂", f"{user_a}:t1", user_id=user_a)
    first = chat("帮我规划10月8日去北京开会3天的行程", f"{user_a}:t1", user_id=user_a)
    assert first.intent == "行程规划" and first.plan is not None

    # B 无常驻城市，规划北京应缺「出发城市」（不得默认用 A 的临沂）
    second = chat("帮我规划10月8日去北京开会3天的行程", f"{user_b}:t1", user_id=user_b)
    assert second.plan is None
    # B 的行程档案不得含 A 的 upcoming 北京行程
    b_trips = memory.get_trips(session_id=user_b)
    assert not any(t["to_city"] == "北京" and t["status"] == "upcoming" for t in b_trips)
    # B 的偏好不得含 A 的常驻城市
    b_prefs = memory.get_preferences(session_id=user_b)
    assert not any(p["category"] == "常驻城市" for p in b_prefs)


@pytest.mark.integration
def test_cross_thread_isolation_same_account():
    """同账号双会话隔离：thread-1 的缺项 drafting 不得污染 thread-2 的新规划。"""
    user = "regr-iso-thread"
    chat("我常住临沂", f"{user}:t1", user_id=user)
    first = chat("去北京出差", f"{user}:t1", user_id=user)  # 有出发/目的地，缺日期天数 → drafting
    assert first.plan is None

    second = chat("10月8日去上海出差3天", f"{user}:t2", user_id=user)  # 新对话
    assert second.intent == "行程规划" and second.plan is not None
    trips = memory.get_trips(session_id=user)
    assert any(t["to_city"] == "上海" and t["status"] == "upcoming" for t in trips), "thread-2 应独立生成上海"
    assert any(t["to_city"] == "北京" and t["status"] == "drafting" for t in trips), "thread-1 的北京 drafting 应保留"


@pytest.mark.integration
def test_duplicate_preference_declaration_is_idempotent():
    """漏洞：重复声明同一偏好（「我喜欢住全季」说两次）会重复落库（is_update 依赖 LLM，不稳定）。

    修复：add_or_update_preference 对 is_update=False 做代码层幂等去重（同 session+category+content）。
    """
    user_id = "regr-pref-dup"
    chat("我喜欢住全季", f"{user_id}:t1", user_id=user_id)
    chat("我喜欢住全季", f"{user_id}:t2", user_id=user_id)
    chat("我喜欢住全季", f"{user_id}:t3", user_id=user_id)
    prefs = memory.get_preferences(session_id=user_id)
    hotel = [p for p in prefs if p["category"] == "住宿"]
    assert [p["content"] for p in hotel] == ["喜欢住全季"], "重复声明相同偏好不得重复追加"


@pytest.mark.integration
def test_preference_update_overrides_not_appends():
    """偏好修改（「我改吃辣了」）覆盖旧偏好（不吃辣→吃辣），不追加。"""
    user_id = "regr-pref-mod"
    chat("我不吃辣", f"{user_id}:t1", user_id=user_id)
    chat("我改吃辣了", f"{user_id}:t2", user_id=user_id)
    prefs = memory.get_preferences(session_id=user_id)
    food = [p for p in prefs if p["category"] == "餐饮"]
    assert len(food) == 1, "修改偏好应覆盖同类别，不追加"
    assert "改" not in food[0]["content"], "content 只存关键名词，不应含「改」语气词"
    assert "辣" in food[0]["content"]
    assert "不吃辣" not in food[0]["content"], "旧偏好应被覆盖"


@pytest.mark.integration
def test_local_time_query_grounded():
    """联网查询扩展：当地时间/时差（get_local_time）走真工具，返回含时区与北京时间差。"""
    user_id = "regr-web-time"
    result = chat("纽约现在几点", f"{user_id}:t1", user_id=user_id)
    assert result.intent == "联网查询"
    _assert_no_reasoning_leak(result.answer)
    assert ("当地时间" in result.answer) or ("比北京" in result.answer) or ("时差" in result.answer)


@pytest.mark.integration
def test_weather_query_includes_uv_feels_like():
    """联网查询扩展：天气查询返回紫外线/体感/风速（穿衣建议所需的扩展字段）。"""
    user_id = "regr-web-weather"
    result = chat("北京明天天气怎么样", f"{user_id}:t1", user_id=user_id)
    assert result.intent == "联网查询"
    _assert_no_reasoning_leak(result.answer)
    assert "°C" in result.answer  # 温度关键事实


@pytest.mark.integration
def test_overseas_trip_budget_and_timezone():
    """海外出差：预算不套本地人民币标准（不出现三线 300 元）、标注当地政策为准、给时差提醒。"""
    user_id = "regr-overseas"
    chat("我常住北京", f"{user_id}:t1", user_id=user_id)
    result = chat("10月8日去纽约出差3天", f"{user_id}:t1", user_id=user_id)
    assert result.intent == "行程规划" and result.plan is not None
    _assert_no_reasoning_leak(result.answer)
    assert "当地差旅政策" in result.answer, "境外预算应标注当地差旅政策为准"
    assert "时差" in result.answer, "跨时区出差应给时差提醒"
    assert "300 元" not in result.answer, "境外不得误套本地三线住宿标准"
