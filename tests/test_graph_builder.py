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
    import xiao_wen.intent as intent_mod
    from xiao_wen.intent import IntentResult

    monkeypatch.setattr(
        intent_mod,
        "classify",
        lambda recent, user_input: IntentResult(intent="临时意图", reason="热插拔测试", subtasks=[]),
    )
    out = after.invoke({"user_input": "x", "recent": "", "messages": []})
    assert out.get("answer") == "临时插件的回答"
