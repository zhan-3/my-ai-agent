"""图工厂（graph_builder）测试：build_supervisor_graph 从注册表 manifest 组装产品图

无 LLM：只断言图结构（节点/路由），不 invoke（invoke 行为由 e2e 集成测试覆盖）。
产品图 = 单意图单路由 + 多意图 Send fan-out / merge fan-in（输入决定是否并行）。
"""

from xiao_wen import graph_builder as gb


def test_graph_has_agents_and_parallel_group():
    """产品图：有分类器、各意图节点、p_* 并行组 + merge"""
    app = gb.build_supervisor_graph()
    nodes = set(app.get_graph().nodes)
    assert "classify_intent" in nodes
    for m in gb.discover():
        assert m["INTENT"] in nodes, f"缺少子 Agent 节点：{m['INTENT']}"
        assert f"p_{m['INTENT']}" in nodes, f"缺少并行组节点：p_{m['INTENT']}"
    assert "merge" in nodes, "产品图应有 merge（fan-in）节点"


def test_graph_has_collect_node():
    """collect-then-compose：产品图必须有 collect_upstream 节点（图级显式收集）"""
    nodes = set(gb.build_supervisor_graph().get_graph().nodes)
    assert "collect_upstream" in nodes


def test_router_reroutes_trip_planning_to_collect():
    """gate 后条件边（未 collect）：含行程规划（主导或 subtasks）→ 先过 collect；否则走原路由"""
    router = gb._make_router()
    # 单意图行程规划 → 收尾者路径
    assert router({"intent": "行程规划", "subtasks": [], "recent": "", "user_input": "x"}) == "collect_upstream"
    # 多意图含行程规划（subtasks）→ 也先 collect
    assert (
        router(
            {
                "intent": "知识问答",
                "subtasks": [gb.SubTask(intent="行程规划", text="y")],
                "recent": "",
                "user_input": "x",
            }
        )
        == "collect_upstream"
    )
    # 不含行程规划 → 原路由不变（字符串直返）
    assert router({"intent": "知识问答", "subtasks": [], "recent": "", "user_input": "x"}) == "知识问答"
    # 消歧短路优先于 collect（歧义时不需要收集）
    assert router({"intent": "行程规划", "subtasks": [], "clarify": True}) == "__clarify_end__"


def test_dispatch_branches_inherit_upstream():
    """多意图 Send 分支必须继承 upstream（否则行程分支读不到 collect 产物）"""
    sends = gb.dispatch(
        {
            "intent": "行程规划",
            "user_input": "x",
            "recent": "r",
            "session_id": "s1",
            "messages": [],
            "subtasks": [gb.SubTask(intent="偏好记录", text="喜欢全季")],
            "upstream": {"policy": "标准文本"},
        }
    )
    assert all(s.arg["upstream"]["policy"] == "标准文本" for s in sends)


def test_invoke_collect_writes_upstream_and_trip_agent_receives(monkeypatch):
    """图 invoke（假 classify/假 agent）：含行程规划 → collect 节点执行写 upstream，
    行程 agent 收到 state["upstream"]（收尾者读黑板）"""
    import types

    from xiao_wen import graph_builder as gb
    from xiao_wen.agents import itinerary_agent

    collected = []

    def fake_collect(user_input, session_id):
        collected.append(user_input)
        return {"policy": "一线城市住宿不超过500", "history_ref": "上次住全季"}

    monkeypatch.setattr(itinerary_agent, "collect_upstream", fake_collect)

    seen = {}

    def fake_run(state):
        seen.update(state)
        return {"answer": "已为你规划行程"}

    monkeypatch.setattr(
        gb,
        "intent",
        types.SimpleNamespace(
            classify=lambda recent, user_input: types.SimpleNamespace(intent="行程规划", reason="t", subtasks=[]),
            set_intents=lambda manifest: None,
        ),
    )
    monkeypatch.setattr(gb, "load_agent", lambda name: types.SimpleNamespace(run=fake_run))

    app = gb.build_supervisor_graph()
    out = app.invoke({"user_input": "去北京开会", "recent": "用户: 你好", "messages": [], "subtasks": []})
    assert collected == ["去北京开会"], "collect 节点应执行一次"
    assert seen.get("upstream") == {"policy": "一线城市住宿不超过500", "history_ref": "上次住全季"}
    assert out["answer"] == "已为你规划行程"


def test_invoke_without_trip_skips_collect(monkeypatch):
    """不含行程规划 → collect 节点不执行（upstream 不写，原路径不变）"""
    import types

    from xiao_wen import graph_builder as gb
    from xiao_wen.agents import itinerary_agent

    collected = []

    def fake_collect(user_input, session_id):
        collected.append(user_input)
        return {"policy": "x"}

    monkeypatch.setattr(itinerary_agent, "collect_upstream", fake_collect)
    monkeypatch.setattr(
        gb,
        "intent",
        types.SimpleNamespace(
            classify=lambda recent, user_input: types.SimpleNamespace(intent="知识问答", reason="t", subtasks=[]),
            set_intents=lambda manifest: None,
        ),
    )
    monkeypatch.setattr(gb, "load_agent", lambda name: types.SimpleNamespace(run=lambda s: {"answer": "标准如下"}))

    app = gb.build_supervisor_graph()
    out = app.invoke({"user_input": "住宿标准是什么", "recent": "用户: 你好", "messages": [], "subtasks": []})
    assert collected == [], "无行程规划不应触发 collect"
    assert out["answer"] == "标准如下"


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


def test_reducer_keeps_first_nonempty():
    """结构化归约器：第一个非空值胜出（单意图直写 / 并行 merge 双来源安全）"""
    plan = {"summary": "s", "days": [], "reasons": []}
    assert gb._first_non_none(None, None) is None
    assert gb._first_non_none(None, plan) == plan
    assert gb._first_non_none(plan, {"summary": "other"}) == plan, "已有 plan 时后续写入不覆盖（主导优先）"


# ---------------- 指纹缓存（热插拔：manifest 变化自动重建） ----------------


def test_same_manifest_returns_cached_graph():
    """manifest 未变：两次 build 返回同一编译图对象（缓存命中，零重建）"""
    a = gb.build_supervisor_graph()
    b = gb.build_supervisor_graph()
    assert a is b


def test_new_plugin_rebuilds_graph(monkeypatch, tmp_path):
    """热插拔：新子 Agent 落盘（注册中心可见）→ 下次 build 自动重建并认识新意图（候选 2 收口）"""
    import xiao_wen.plugin_registry as pr

    monkeypatch.setattr(pr, "PLUGIN_DIR", tmp_path)  # 外部扩展目录指向临时目录
    import xiao_wen.intent as intent_mod

    monkeypatch.setattr(intent_mod, "_current_intents", None)  # 隔离词汇表注入副作用（build→set_intents）
    before = gb.build_supervisor_graph()
    before_nodes = set(before.get_graph().nodes)
    assert "临时意图" not in before_nodes

    (tmp_path / "tmp_plugin.py").write_text(
        'INTENT = "临时意图"\nDESCRIPTION = "临时插件：验证热插拔"\n'
        'def run(state):\n    return {"answer": "临时插件的回答"}\n',
        encoding="utf-8",
    )
    after = gb.build_supervisor_graph()
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

    gb.build_supervisor_graph()  # 指纹变化 → 重建 → 应重新注入词汇表
    assert intent_mod._current_intents is not None, "图工厂重建应重新注入词汇表（set_intents）"
    assert intent_mod._intent_model.cache_info().currsize == 0, "词汇表刷新必须失效模型缓存"


def test_build_refreshes_vocabulary_with_new_plugin(monkeypatch, tmp_path):
    """落盘新子 Agent → 重建后词汇表包含新意图（warm 语义，不 monkeypatch classify）"""
    import xiao_wen.intent as intent_mod
    import xiao_wen.plugin_registry as pr

    monkeypatch.setattr(pr, "PLUGIN_DIR", tmp_path)
    monkeypatch.setattr(intent_mod, "_current_intents", [])  # 重置注入状态，teardown 自动恢复
    gb.build_supervisor_graph()
    assert "临时意图" not in {m["INTENT"] for m in intent_mod._current_intents or []}

    (tmp_path / "tmp_plugin.py").write_text(
        'INTENT = "临时意图"\nDESCRIPTION = "临时插件：验证词汇表刷新"\n'
        'def run(state):\n    return {"answer": "临时插件的回答"}\n',
        encoding="utf-8",
    )
    gb.build_supervisor_graph()
    assert "临时意图" in {m["INTENT"] for m in intent_mod._current_intents or []}


# ---- 轻量消歧：clarify_gate 节点 + 路由 ----
def test_graph_has_clarify_gate():
    """产品图应含 clarify_gate（classify 与路由之间）"""
    nodes = set(gb.build_supervisor_graph().get_graph().nodes)
    assert "clarify_gate" in nodes


def test_clarify_gate_returns_question_on_ambiguous():
    """消歧门：命中歧义 → clarify=True + answer=反问问题"""
    out = gb.clarify_gate({"user_input": "帮我查一下回程日期有没有航班", "intent": "行程规划"})
    assert out["clarify"] is True
    assert "①" in out["answer"] and "②" in out["answer"]


def test_clarify_gate_passthrough_when_clear():
    """消歧门：未命中 → clarify=False，不触碰 answer（原路由继续）"""
    out = gb.clarify_gate({"user_input": "帮我订一张去北京的机票", "intent": "行程规划"})
    assert out == {"clarify": False}


def test_router_short_circuits():
    """产品图路由（collect 后）：命中 → __clarify_end__（短路 END）；未命中 → 原 dispatch 结果不变"""
    router = gb._make_router(after_collect=True)
    assert router({"clarify": True}) == "__clarify_end__"
    assert router({"clarify": False, "intent": "知识问答", "subtasks": []}) == "知识问答"
    # 多意图：Send fan-out 不变
    subs = [gb.SubTask(intent="联网查询", text="北京天气")]
    state = {"clarify": False, "intent": "行程规划", "user_input": "帮我规划行程，顺便查北京天气", "subtasks": subs}
    sends = router(state)
    assert isinstance(sends, list) and all(hasattr(s, "node") for s in sends)
