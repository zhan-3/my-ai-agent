"""消歧规则单测：纯函数，无 LLM（disambiguation.clarify）

正例：航班信息类（查/有没有航班，非订买）→ 反问；咨询建议类（住哪里比较好）→ 反问
反例：订/买票动作、明确规划、个人休闲、政策标准查询 → 不触发
"""

from xiao_wen.disambiguation import clarify


# ---- 触发器 A：航班/车次信息类（意图=行程规划） ----
def test_flight_info_query_clarifies():
    q = clarify("帮我查一下回程日期有没有航班", "行程规划")
    assert q and "①" in q and "②" in q and "航班" in q


def test_flight_query_with_date_clarifies():
    q = clarify("帮我查查10月8日有没有去深圳的航班", "行程规划")
    assert q


def test_train_schedule_clarifies():
    q = clarify("明天有没有去北京的高铁", "行程规划")
    assert q


def test_booking_action_no_clarify():
    assert clarify("帮我订一张去北京的机票", "行程规划") is None


def test_planning_without_flight_no_clarify():
    assert clarify("帮我规划10月1日去广州出差2天的行程", "行程规划") is None


def test_non_planning_intent_no_flight_clarify():
    assert clarify("帮我查一下明天北京天气", "联网查询") is None


# ---- 触发器 B：咨询建议类（意图=其他） ----
def test_advice_question_clarifies():
    q = clarify("出差住哪里比较好", "其他")
    assert q and "①" in q


# ---- 触发器 C：选项应答（确定性，需 recent 含上一轮航班反问） ----
_FLIGHT_RECENT = (
    "user: 帮我查一下回程日期有没有航班\nassistant: 你是想①查航班/车次时刻信息，还是②规划含这段出行的行程？"
)


def test_option_one_after_flight_question_answers_honestly():
    q = clarify("①", "行程规划", recent=_FLIGHT_RECENT)
    assert q and "暂不支持" in q and "航班" in q


def test_option_one_digit_variant():
    q = clarify("1", "行程规划", recent=_FLIGHT_RECENT)
    assert q and "暂不支持" in q


def test_option_two_passes_through_to_intent_resolution():
    """② 不拦截——放行正常意图解析（LLM 从上下文消解为行程规划）"""
    assert clarify("②", "行程规划", recent=_FLIGHT_RECENT) is None


def test_option_without_flight_question_no_hijack():
    """没反问过航班时，不能拦截裸『1』等输入"""
    assert clarify("1", "行程规划", recent="") is None
    assert clarify("①", "行程规划", recent="user: 随便聊聊") is None


def test_recommendation_clarifies():
    assert clarify("北京出差住哪家酒店好？推荐一下", "其他") is not None


def test_lifestyle_no_clarify():
    assert clarify("杭州有什么好玩的", "其他") is None


def test_advice_without_travel_ctx_no_clarify():
    assert clarify("有什么推荐的吗", "其他") is None


# ---- 其他意图不触发 ----
def test_policy_query_no_clarify():
    assert clarify("二线城市住宿标准是多少", "知识问答") is None


def test_history_query_no_clarify():
    assert clarify("我上次的行程是什么", "历史查询") is None
