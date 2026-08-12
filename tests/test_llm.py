"""LLM 接缝测试：懒加载 / 校验快速失败 / 熔断守卫 / 透传（全本地，不碰真实 LLM）"""

import importlib
from typing import cast

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from xiao_wen import llm
from xiao_wen.stability import CircuitBreaker


@pytest.fixture(autouse=True)
def _fresh_breaker(monkeypatch):
    """每个用例独立熔断器，避免测试间互相污染全局状态"""
    monkeypatch.setattr(llm, "_breaker", CircuitBreaker())


class FakeLLM:
    """测试桩：满足 get_llm override 所需的最小 LLM 面（invoke + 链式方法），非真 BaseChatModel"""

    def __init__(self, answer="ok", fail=None):
        self.answer = answer
        self.fail = fail
        self.invokes = 0

    def invoke(self, *args, **kwargs):
        self.invokes += 1
        if self.fail:
            raise self.fail
        return self.answer

    def with_structured_output(self, *args, **kwargs):
        return self

    def bind_tools(self, *args, **kwargs):
        return self


def _llm_override(fake: FakeLLM) -> BaseChatModel:
    """测试注入：FakeLLM → BaseChatModel（结构满足 get_llm 所需面，非真实现）"""
    return cast(BaseChatModel, fake)


def _drop_env(monkeypatch):
    for v in llm.REQUIRED_ENV_VARS:
        monkeypatch.delenv(v, raising=False)


def test_import_does_not_read_env(monkeypatch):
    """懒加载：无环境变量时模块导入必须成功（构造只发生在首次 get_llm()）"""
    _drop_env(monkeypatch)
    mod = importlib.reload(llm)
    assert hasattr(mod, "get_llm")
    assert mod._default_model.cache_info().currsize == 0  # 默认模型尚未构造


def test_validation_lists_all_missing(monkeypatch):
    _drop_env(monkeypatch)
    with pytest.raises(RuntimeError) as e:
        llm.get_llm()
    for v in llm.REQUIRED_ENV_VARS:
        assert v in str(e.value)


def test_override_skips_validation(monkeypatch):
    _drop_env(monkeypatch)
    m = llm.get_llm(override=_llm_override(FakeLLM()))
    assert m.invoke("hi") == "ok"


def test_breaker_fail_fast(monkeypatch):
    fake = FakeLLM(fail=RuntimeError("boom"))
    m = llm.get_llm(override=_llm_override(fake))
    for _ in range(3):
        with pytest.raises(RuntimeError):
            m.invoke("x")
    assert fake.invokes == 3
    # 熔断打开：快速失败，不再调内层
    with pytest.raises(RuntimeError, match="熔断已打开"):
        m.invoke("x")
    assert fake.invokes == 3


def test_success_resets_breaker(monkeypatch):
    fake = FakeLLM(fail=RuntimeError("boom"))
    m = llm.get_llm(override=_llm_override(fake))
    for _ in range(2):
        with pytest.raises(RuntimeError):
            m.invoke("x")
    fake.fail = None
    assert m.invoke("ok") == "ok"  # 成功 → 计数清零
    fake.fail = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        m.invoke("x")  # 失败计数从 0 重新累计，不立刻熔断


def test_guard_wraps_derived_and_passthrough(monkeypatch):
    class Structured:
        def invoke(self, *a, **k):
            return "structured"

    fake = FakeLLM()
    fake.with_structured_output = lambda schema, **k: Structured()  # type: ignore[method-assign]
    fake.bind_tools = lambda *a, **k: object()  # type: ignore[method-assign]

    m = llm.get_llm(override=_llm_override(fake))
    s = m.with_structured_output(dict)
    assert isinstance(s, llm._GuardedLLM)
    assert s.invoke("x") == "structured"
    b = m.bind_tools([])
    assert isinstance(b, llm._GuardedLLM)
    assert m.invokes == 0  # 派生包装不触发调用


def test_prompt_composition_inherits_guard(monkeypatch):
    """回归：prompt | get_llm(override=...) 必须能组合（Runnable 子类），且链调用走熔断"""
    from langchain_core.prompts import ChatPromptTemplate

    fake = FakeLLM(answer='{"intent": "行程规划", "reason": "测试"}')
    chain = ChatPromptTemplate.from_messages([("human", "{input}")]) | llm.get_llm(override=_llm_override(fake))
    assert chain.invoke({"input": "hi"}) == fake.answer
    assert fake.invokes == 1

    # 链上结构化输出同样可组合且走守卫
    class Structured:
        def invoke(self, *a, **k):
            return "struct"

    fake.with_structured_output = lambda schema, **k: Structured()  # type: ignore[method-assign]
    chain2 = ChatPromptTemplate.from_messages([("human", "{input}")]) | llm.get_llm(
        override=_llm_override(fake)
    ).with_structured_output(dict)
    assert chain2.invoke({"input": "hi"}) == "struct"


def test_chain_breaker_fail_fast(monkeypatch):
    """回归：链调用 3 次失败后熔断打开，后续链调用快速失败不再调内层"""
    from langchain_core.prompts import ChatPromptTemplate

    fake = FakeLLM(fail=RuntimeError("boom"))
    chain = ChatPromptTemplate.from_messages([("human", "{input}")]) | llm.get_llm(override=_llm_override(fake))
    for _ in range(3):
        with pytest.raises(RuntimeError):
            chain.invoke({"input": "x"})
    with pytest.raises(RuntimeError, match="熔断已打开"):
        chain.invoke({"input": "x"})
    assert fake.invokes == 3
