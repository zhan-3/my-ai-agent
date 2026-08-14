"""端到端集成测试（真实 LLM + 真实记忆文件，隔离到 tmp）：
两层记忆闭环 —— 偏好新增 → 常驻城市补全 → 行程规划 → 历史查询；
产品默认图（调度图）—— 单意图回归 + 多意图并行派发

跑法：uv run pytest -m integration
"""

import pytest

from xiao_wen.graph_builder import build_supervisor_graph

_app = build_supervisor_graph(parallel=True)  # 产品默认图（session.chat 同一实例）


def _invoke(user_input: str) -> str:
    """走完整图（含记忆读写），返回 answer 文本"""
    state = {"user_input": user_input, "recent": ""}
    out = _app.invoke(state)
    return out.get("answer", "")


@pytest.mark.integration
def test_two_layer_memory_loop():
    # ① 偏好记录（长期记忆）
    ans = _invoke("我不吃辣，住宿喜欢安静")
    assert "已新增偏好" in ans

    # ② 常驻城市（覆盖式长期记忆）
    ans = _invoke("我现在常住上海")
    assert "已更新偏好" in ans

    # ③ 行程规划：不说出发城市 → 常驻城市补全（长期记忆生效）
    ans = _invoke("5月8日去北京开会4天")
    assert "上海" in ans, "应自动补全出发城市（长期记忆常驻城市）"

    # ④ 历史查询（长期记忆历史行程可读）
    ans = _invoke("我上次的行程是什么")
    assert "北京" in ans

    # ⑤ 边界：个人休闲 → 其他
    ans = _invoke("这个暑假去哪里玩")
    assert "服务范围" in ans or "抱歉" in ans


@pytest.mark.integration
def test_external_agent_end_to_end_dispatch():
    """外部扩展子 Agent（差旅统计）经真实主管图端到端派发：
    注册表发现 → 词汇表注入 → 意图识别 → 条件边路由 → 懒加载执行"""
    ans = _invoke("统计一下我的出差情况")
    assert "暂无历史行程记录" in ans, f"期望 stats.run 输出，实际：{ans}"


@pytest.mark.integration
def test_parallel_multi_intent_end_to_end():
    """多意图并行（产品默认图 = 调度图）：一句话拆两个子任务 → Send fan-out → merge 汇总
    （Q7：并行能力进产品的验收——单意图回归由其余 e2e 覆盖）"""
    ans = _invoke("帮我查下出差住宿标准是什么，顺便看看北京今天天气怎么样")
    assert "2 个请求" in ans, f"期望并行汇总文案，实际：{ans}"
    assert "住宿标准" in ans and "北京" in ans, f"两个子任务的回答都应汇总：{ans}"


@pytest.mark.integration
def test_disambiguation_multi_turn():
    """轻量消歧多轮闭环（真实 LLM + 产品图 + 记忆写回）：
    turn1 航班信息查询 → 反问带选项；turn2 选② → 消解为行程规划；turn3 选① → 无工具诚实归其他"""
    from xiao_wen.session import chat

    # turn 1：信息类航班查询 → 消歧门反问（不硬猜成规划任务）
    r1 = chat("帮我查一下回程日期有没有航班")
    assert "①" in r1.answer and "②" in r1.answer, f"期望带选项反问，实际：{r1.answer}"

    # turn 2：用户选②（规划含航班的行程）→ 上下文消解 → 行程规划（要素缺失追问）
    r2 = chat("②")
    assert r2.intent == "行程规划", f"② 应消解为行程规划，实际 {r2.intent}（{r2.reason}）"
    assert "①" not in r2.answer, "已消解，不应再反问"

    # turn 3（新会话）：用户选①（查时刻）→ 确定性诚实答复

    r3 = chat("帮我查一下明天上午有没有航班", session_id="disambig-info")
    assert "①" in r3.answer, "信息类航班查询应再次反问，实际：" + r3.answer
    # 用户选①（查时刻）→ 确定性诚实答复（不静默进行程规划追问，也不依赖 LLM 意图）
    r4 = chat("①", session_id="disambig-info")
    assert "暂不支持" in r4.answer and "航班" in r4.answer, "① 应诚实告知不支持，实际：" + r4.answer


# ==================== E2E 场景矩阵（ticket 05：E2E-05 ~ E2E-08） ====================


@pytest.mark.integration
def test_policy_qa_end_to_end():
    """E2E-05 差旅政策知识问答（RAG）：问住宿标准 → 知识问答给出政策数值"""
    ans = _invoke("出差住宿标准是什么")
    assert "标准" in ans or "元" in ans, f"期望政策标准答案，实际：{ans}"


@pytest.mark.integration
def test_web_query_end_to_end():
    """E2E-06 联网天气查询：指定城市实时信息 → 联网查询（ReAct 工具）"""
    ans = _invoke("北京今天天气怎么样")
    assert "北京" in ans, f"答案应含城市名，实际：{ans}"
    assert any(k in ans for k in ("℃", "度", "晴", "雨", "多云", "天气")), f"答案应含天气信息，实际：{ans}"


@pytest.mark.integration
def test_missing_elements_multi_turn_planning():
    """E2E-07 缺项追问→补齐→生成→历史按城市过滤（四轮闭环）"""
    from xiao_wen.session import chat

    # 轮1：只给目的城市 → 缺项追问（出发城市/日期/天数）
    r1 = chat("帮我规划去杭州出差的行程")
    assert "请补充" in r1.answer, f"期望缺项追问，实际：{r1.answer}"

    # 轮2：补齐要素 → 生成行程（含杭州与日期）
    r2 = chat("5月8日从上海出发，待2天")
    assert "杭州" in r2.answer, f"生成行程应含杭州，实际：{r2.answer}"
    assert "5月8日" in r2.answer, f"生成行程应含日期，实际：{r2.answer}"
    assert "请补充" not in r2.answer, "要素已齐，不应再追问"

    # 轮3：历史按城市过滤 → 命中刚生成的杭州行程
    r3 = chat("我最近去杭州的行程")
    assert "杭州" in r3.answer and "5月8日" in r3.answer, f"历史应命中杭州行程，实际：{r3.answer}"


@pytest.mark.integration
def test_advice_disambiguation_end_to_end():
    """E2E-08 消歧 B（咨询建议类）：出差住哪里比较好 → 门控反问（①政策/②按偏好）"""
    ans = _invoke("出差住哪里比较好")
    assert "①" in ans and "政策" in ans, f"期望消歧反问（①政策 ②偏好），实际：{ans}"
