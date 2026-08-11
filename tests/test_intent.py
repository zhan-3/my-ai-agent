"""意图识别集成测试（真实 LLM，加分项 E 的「对意图识别进行验证」）

跑法：uv run pytest -m integration
"""
import importlib.util
import os

import pytest

sys_path = os.path.join(os.path.dirname(__file__), "..", "homework")
_spec = importlib.util.spec_from_file_location(
    "sys_mod", os.path.join(sys_path, "0010_system.py"))
_sys = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sys)

# 典型用例：从 0004/0010 的验证用例固化而来（含产品边界：个人休闲 → 其他）
CASES = [
    ("10月8日去北京开会4天", "行程规划"),
    ("我不吃辣，住宿喜欢安静", "偏好记录"),
    ("我上次的行程是什么", "历史查询"),
    ("出差住宿标准是什么", "知识问答"),
    ("北京今天天气怎么样", "联网查询"),
    ("这个暑假去哪里玩", "其他"),
    ("我想去三亚度假两周", "其他"),      # 产品边界：个人休闲游 → 其他
]


@pytest.mark.integration
@pytest.mark.parametrize("text,expected", CASES)
def test_intent_classification(text, expected):
    r = _sys.intent_model.invoke({"recent": "", "input": text})
    assert isinstance(r, _sys.Intent)
    assert r.intent == expected, f"{text!r} 期望 {expected}，实际 {r.intent}（{r.reason}）"
