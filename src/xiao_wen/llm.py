"""LLM 单一接缝：全系统模型构造的唯一入口（ADR-0001）

- 懒构造：模块导入不读环境变量，首次 get_llm() 才校验并构造（默认实例缓存复用）
- 快速失败：缺少 DEEPSEEK_* 时一次性列出全部缺失变量（不再让 KeyError 蒙在鼓里）
- 熔断守卫：返回的模型经 _GuardedLLM 薄代理包裹，invoke 走共享 CircuitBreaker；
  bind_tools / with_structured_output 的派生对象同样被守卫——一处守卫，全部链继承
- 注入点：override 参数供测试传假模型（跳过 env 校验）；overrides 覆盖默认构造参数
"""

from functools import lru_cache
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from xiao_wen.config import LLM_ENV_VARS, load_settings
from xiao_wen.stability import CircuitBreaker

# 接缝校验的环境变量（唯一来源；health_check 复用见 C7）
REQUIRED_ENV_VARS = LLM_ENV_VARS

_DEFAULT_CONFIG: dict[str, Any] = {
    "temperature": 0,
    "max_retries": 2,  # 工程稳定性：LLM 失败自动重试 2 次
    "timeout": 30,  # 工程稳定性：30s 无响应即放弃
    "extra_body": {"thinking": {"type": "disabled"}},
}

# 共享熔断器：进程级全局（ADR-0001：单用户演示可接受）
_breaker = CircuitBreaker(failure_threshold=3, recovery_time=5.0)


class _GuardedLLM(Runnable):
    """薄代理：invoke 走共享熔断器，其余能力由 Runnable 基类默认实现经 invoke 合成，
    with_structured_output / bind_tools 显式委托内层（保持 ChatOpenAI 语义）——
    一处守卫，全部链继承熔断。"""

    def __init__(self, inner):
        super().__init__()
        self._inner = inner

    def invoke(self, input, config=None, **kwargs):
        if _breaker.is_open:
            raise RuntimeError("服务熔断已打开（LLM 连续失败），请稍后再试")
        try:
            result = self._inner.invoke(input, config=config, **kwargs)
        except Exception:
            _breaker.record_failure()
            raise
        _breaker.record_success()
        return result

    def with_structured_output(self, *args, **kwargs):
        return _GuardedLLM(self._inner.with_structured_output(*args, **kwargs))

    def bind_tools(self, *args, **kwargs):
        return _GuardedLLM(self._inner.bind_tools(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _validate_env() -> None:
    load_settings().require_llm()


@lru_cache
def _default_model() -> ChatOpenAI:
    llm_config = load_settings().require_llm()
    return ChatOpenAI(
        model=llm_config.model,
        base_url=llm_config.base_url,
        api_key=SecretStr(llm_config.api_key),
        **_DEFAULT_CONFIG,
    )


def get_llm(*, override: BaseChatModel | None = None, **overrides) -> _GuardedLLM:
    """模型单一接缝：返回熔断守卫的 LLM 代理

    - override：测试注入假模型 / 故障模型（跳过 env 校验）
    - overrides：覆盖默认构造参数（如 max_retries=1, timeout=10），每次现构
    """
    if override is not None:
        return _GuardedLLM(override)
    if overrides:
        llm_config = load_settings().require_llm()
        config = {**_DEFAULT_CONFIG, **overrides}
        return _GuardedLLM(
            ChatOpenAI(
                model=llm_config.model,
                base_url=llm_config.base_url,
                api_key=SecretStr(llm_config.api_key),
                **config,
            )
        )
    return _GuardedLLM(_default_model())
