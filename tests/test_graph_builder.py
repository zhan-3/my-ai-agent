"""图工厂（graph_builder）测试：build_supervisor_graph 从注册表 manifest 组装主管/调度图

无 LLM：只断言图结构（节点/路由），不 invoke（invoke 行为由 e2e 集成测试覆盖）。
"""

from xiao_wen import graph_builder as gb


def test_single_intent_graph_has_no_parallel_group():
    """parallel=False：单意图主管图——有分类器与各意图节点，无 p_* / merge"""
    app = gb.build_supervisor_graph(parallel=False)
    nodes = set(app.get_graph().nodes)
    assert "classify_intent" in nodes
    for m in gb.discover():
        assert m["INTENT"] in nodes, f"缺少子 Agent 节点：{m['INTENT']}"
    assert not any(n.startswith("p_") for n in nodes), "单意图图不应有并行组节点"
    assert "merge" not in nodes, "单意图图不应有 merge 节点"


def test_parallel_graph_has_parallel_group():
    """parallel=True：调度图——在单意图图基础上增加 p_* 并行组 + merge"""
    app = gb.build_supervisor_graph(parallel=True)
    nodes = set(app.get_graph().nodes)
    assert "classify_intent" in nodes
    for m in gb.discover():
        assert f"p_{m['INTENT']}" in nodes, f"缺少并行组节点：p_{m['INTENT']}"
    assert "merge" in nodes, "调度图应有 merge（fan-in）节点"


def test_parallel_is_superset_of_single():
    """parallel=True 图包含 parallel=False 图的所有业务节点（并行是增强，不破坏单意图）"""
    single = set(gb.build_supervisor_graph(parallel=False).get_graph().nodes)
    parallel = set(gb.build_supervisor_graph(parallel=True).get_graph().nodes)
    business = single - {"__start__", "__end__"}
    assert business <= parallel, f"调度图缺失单意图图的业务节点：{business - parallel}"


def test_merge_picks_first_nonempty_plan():
    """并行 merge：多路结果中取第一个非空 plan（主导意图优先，其余分支无 plan）"""
    plan = {"summary": "北京出差", "days": [], "reasons": []}
    out = gb.merge(
        {
            "collected": [
                {"intent": "偏好记录", "text": "x", "answer": "记好了", "plan": None},
                {"intent": "行程规划", "text": "y", "answer": "行程如下", "plan": plan},
                {"intent": "知识问答", "text": "z", "answer": "标准如下", "plan": None},
            ]
        }
    )
    assert out["plan"] == plan
    assert "同时为你处理了 3 个请求" in out["answer"]


def test_merge_without_plan_returns_none():
    """并行 merge：无任何分支产出 plan → plan 为 None（前端走文本回退渲染）"""
    out = gb.merge(
        {
            "collected": [
                {"intent": "知识问答", "text": "q", "answer": "标准如下", "plan": None},
            ]
        }
    )
    assert out["plan"] is None


def test_plan_reducer_keeps_first_nonempty():
    """plan 归约器：第一个非空值胜出（单意图直写 / 并行 merge 双来源安全）"""
    plan = {"summary": "s", "days": [], "reasons": []}
    assert gb._first_plan(None, None) is None
    assert gb._first_plan(None, plan) == plan
    assert gb._first_plan(plan, {"summary": "other"}) == plan, "已有 plan 时后续写入不覆盖（主导优先）"


# ---------------- 指纹缓存（热插拔：manifest 变化自动重建） ----------------


def test_same_manifest_returns_cached_graph():
    """manifest 未变：两次 build 返回同一编译图对象（缓存命中，零重建）"""
    a = gb.build_supervisor_graph(parallel=False)
    b = gb.build_supervisor_graph(parallel=False)
    assert a is b
    c = gb.build_supervisor_graph(parallel=True)
    d = gb.build_supervisor_graph(parallel=True)
    assert c is d
    assert a is not c  # parallel 参数不同是不同代


def test_new_plugin_rebuilds_graph(monkeypatch, tmp_path):
    """热插拔：新子 Agent 落盘（注册中心可见）→ 下次 build 自动重建并认识新意图（候选 2 收口）"""
    import xiao_wen.plugin_registry as pr

    monkeypatch.setattr(pr, "PLUGIN_DIR", tmp_path)  # 外部扩展目录指向临时目录
    import xiao_wen.intent as intent_mod

    monkeypatch.setattr(intent_mod, "_current_intents", None)  # 隔离词汇表注入副作用（build→set_intents）
    before = gb.build_supervisor_graph(parallel=False)
    before_nodes = set(before.get_graph().nodes)
    assert "临时意图" not in before_nodes

    (tmp_path / "tmp_plugin.py").write_text(
        'INTENT = "临时意图"\nDESCRIPTION = "临时插件：验证热插拔"\n'
        'def run(state):\n    return {"answer": "临时插件的回答"}\n',
        encoding="utf-8",
    )
    after = gb.build_supervisor_graph(parallel=False)
    assert after is not before  # manifest 变化 → 重建（不同图对象）
    after_nodes = set(after.get_graph().nodes)
    assert "临时意图" in after_nodes  # 新意图进入图

    # 懒加载派发：短路意图分类（无 LLM），验证新意图可路由到临时插件
    from xiao_wen.intent import IntentResult

    monkeypatch.setattr(
        intent_mod,
        "classify",
        lambda recent, user_input: IntentResult(intent="临时意图", reason="热插拔测试", subtasks=[]),
    )
    out = after.invoke({"user_input": "x", "recent": "", "messages": []})
    assert out.get("answer") == "临时插件的回答"


def test_build_reinjects_vocabulary_and_invalidates_intent_model(monkeypatch, tmp_path):
    """warm 进程热插拔回归（Standards/Spec 双轴同钉）：图工厂重建必须同时
    刷新意图词汇表并失效 _intent_model 缓存——否则常驻进程（webapp）中
    新子 Agent 落盘后词汇表冻结，新意图永远归「其他」"""
    import xiao_wen.intent as intent_mod
    import xiao_wen.plugin_registry as pr

    monkeypatch.setattr(pr, "PLUGIN_DIR", tmp_path)
    monkeypatch.setattr(intent_mod, "_current_intents", [])  # 重置注入状态（空词汇表，teardown 自动恢复）
    # CI 无 .env（gitignored）→ _intent_model 构造模型需 env；此处只构造 prompt 不发请求
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ci-fake-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("DEEPSEEK_MODEL", "fake-model")
    intent_mod._intent_model()  # 预热：缓存一个 prompt（基线词汇表）
    assert intent_mod._intent_model.cache_info().currsize == 1

    gb.build_supervisor_graph(parallel=False)  # 指纹变化 → 重建 → 应重新注入词汇表
    assert intent_mod._current_intents is not None, "图工厂重建应重新注入词汇表（set_intents）"
    assert intent_mod._intent_model.cache_info().currsize == 0, "词汇表刷新必须失效模型缓存"


def test_build_refreshes_vocabulary_with_new_plugin(monkeypatch, tmp_path):
    """落盘新子 Agent → 重建后词汇表包含新意图（warm 语义，不 monkeypatch classify）"""
    import xiao_wen.intent as intent_mod
    import xiao_wen.plugin_registry as pr

    monkeypatch.setattr(pr, "PLUGIN_DIR", tmp_path)
    monkeypatch.setattr(intent_mod, "_current_intents", [])  # 重置注入状态，teardown 自动恢复
    gb.build_supervisor_graph(parallel=False)
    assert "临时意图" not in {m["INTENT"] for m in intent_mod._current_intents or []}

    (tmp_path / "tmp_plugin.py").write_text(
        'INTENT = "临时意图"\nDESCRIPTION = "临时插件：验证词汇表刷新"\n'
        'def run(state):\n    return {"answer": "临时插件的回答"}\n',
        encoding="utf-8",
    )
    gb.build_supervisor_graph(parallel=False)
    assert "临时意图" in {m["INTENT"] for m in intent_mod._current_intents or []}


# ---- 轻量消歧：clarify_gate 节点 + 路由 ----
def test_graphs_have_clarify_gate():
    """两图都应含 clarify_gate（classify 与路由之间）"""
    for parallel in (False, True):
        nodes = set(gb.build_supervisor_graph(parallel=parallel).get_graph().nodes)
        assert "clarify_gate" in nodes, f"parallel={parallel} 图缺少 clarify_gate 节点"


def test_clarify_gate_returns_question_on_ambiguous():
    """消歧门：命中歧义 → clarify=True + answer=反问问题"""
    out = gb.clarify_gate({"user_input": "帮我查一下回程日期有没有航班", "intent": "行程规划"})
    assert out["clarify"] is True
    assert "①" in out["answer"] and "②" in out["answer"]


def test_clarify_gate_passthrough_when_clear():
    """消歧门：未命中 → clarify=False，不触碰 answer（原路由继续）"""
    out = gb.clarify_gate({"user_input": "帮我订一张去北京的机票", "intent": "行程规划"})
    assert out == {"clarify": False}


def test_route_after_gate_short_circuits():
    """并行图路由：命中 → __clarify_end__（短路 END）；未命中 → 原 dispatch 结果不变"""
    assert gb.route_after_gate({"clarify": True}) == "__clarify_end__"
    assert gb.route_after_gate({"clarify": False, "intent": "知识问答", "subtasks": []}) == "知识问答"
    # 多意图：Send fan-out 不变
    subs = [gb.SubTask(intent="联网查询", text="北京天气")]
    state = {"clarify": False, "intent": "行程规划", "user_input": "帮我规划行程，顺便查北京天气", "subtasks": subs}
    sends = gb.route_after_gate(state)
    assert isinstance(sends, list) and all(hasattr(s, "node") for s in sends)


def test_route_after_gate_serial_short_circuits():
    """单意图图路由：命中 → 短路；未命中 → 原字符串路由不变"""
    assert gb.route_after_gate_serial({"clarify": True}) == "__clarify_end__"
    assert gb.route_after_gate_serial({"clarify": False, "intent": "行程规划"}) == "行程规划"
