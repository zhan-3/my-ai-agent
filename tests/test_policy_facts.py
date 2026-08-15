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
