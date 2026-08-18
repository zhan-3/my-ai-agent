from xiao_wen import rag


def test_policy_context_extracts_supported_facts_with_evidence_ids():
    context = rag.policy_context_from_texts(
        "出差标准",
        [("01_travel_standards", "一线城市住宿标准：不超过500元/晚；早餐不超过30元/餐；午餐和晚餐每餐不超过100元")],
    )
    facts = {fact.key: fact for fact in context.facts}
    assert context.status == "grounded"
    assert context.snapshot_id
    assert facts["hotel_rate"].value == 500
    assert facts["hotel_rate"].scope == {"city_tier": "一线"}
    assert facts["hotel_rate"].evidence_ids == context.evidence_ids
    assert facts["breakfast_rate"].value == 30
    assert facts["meal_rate"].value == 100


def test_policy_context_without_evidence_is_not_found():
    context = rag.policy_context_from_texts("住宿标准", [])
    assert context.status == "not_found"
    assert context.facts == ()
    assert context.evidence_ids == ()


def test_policy_context_marks_expired_evidence_stale():
    context = rag.policy_context_from_texts(
        "住宿标准", [("policy-v1", "版本 1.0；一线城市住宿标准不超过500元/晚；有效期至 2020-01-01")]
    )
    assert context.status == "stale"
    assert context.facts == ()


def test_policy_context_marks_conflicting_facts_ambiguous():
    context = rag.policy_context_from_texts(
        "住宿标准",
        [
            ("policy-v1", "一线城市住宿标准不超过500元/晚"),
            ("policy-v2", "一线城市住宿标准不超过800元/晚"),
        ],
    )
    assert context.status == "ambiguous"
    assert context.facts == ()


def test_policy_context_extracts_train_seat_standard_consistently():
    """「允许预订：二等座及以下」在两个文档中一致 → 不误判冲突。

    分块合并换行后，正则若贪婪匹配会吞掉后续列表项（两种「特殊情况」措辞不同），
    导致同一事实在两个来源里 value 不同而被误判 ambiguous（曾让「火车票能订什么座位」拒答）。
    """
    context = rag.policy_context_from_texts(
        "火车票座位等级",
        [
            (
                "01_travel_standards",
                "高铁/动车标准 - 允许预订：二等座及以下 - 特殊情况可申请商务座 - 夜间出行可选择卧铺",
            ),
            (
                "03_booking_guide",
                "座位等级 - 允许预订：二等座及以下 - 特殊情况：长途夜间出行可申请卧铺 - 商务座需特别申请",
            ),
        ],
    )
    assert context.status == "grounded"
    seat = {f.key: f for f in context.facts}["train_seat_standard"]
    assert seat.value == "二等座及以下"
