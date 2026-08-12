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
    ans = _invoke("10月8日去北京开会4天")
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
