"""稳定性演示：重试 / 超时 / 熔断 / 故障注入 / 健康检查

跑法：uv run python -m xiao_wen.demos.stability_demo
四幕演示：
  幕1 重试+超时：偶发失败的调用 → 指数退避重试后成功（日志为证）
  幕2 熔断三态：持续失败 → 熔断打开 → 快速失败不耗时 → 半开试探恢复
  幕3 真实系统故障注入：把 system 的 LLM 换成坏 key → 裸调用崩 vs 稳定性层降级
  幕4 健康检查：系统自检报告
"""

import os
import time

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from xiao_wen.stability import CircuitBreaker, health_check, with_retry

load_dotenv()

# 造一个"故障注入用"的 LLM：key 故意写错
BAD_LLM = ChatOpenAI(
    model=os.environ["DEEPSEEK_MODEL"],
    base_url=os.environ["DEEPSEEK_BASE_URL"],
    api_key=SecretStr("sk-invalid-key-for-demo"),
    temperature=0,
    max_retries=1,  # 重试：LangChain 内置（真实 LLM 失败自动重试 1 次）
    timeout=10,  # 超时：10s 无响应即放弃（超时控制）
    extra_body={"thinking": {"type": "disabled"}},
)

if __name__ == "__main__":
    print("=" * 60)
    print("幕1｜重试（指数退避）+ 超时控制")
    flaky_calls = {"n": 0}

    @with_retry(retries=2, base_delay=0.3)
    def flaky_llm() -> str:
        """前 2 次模拟网络闪断，第 3 次成功"""
        flaky_calls["n"] += 1
        if flaky_calls["n"] < 3:
            raise ConnectionError("网络闪断（模拟）")
        return "第 3 次终于成功了"

    try:
        out = flaky_llm()
        print(f"  → 重试 {flaky_calls['n'] - 1} 次后成功：{out}")
    except Exception as e:
        print(f"  ✗ 失败：{e}")
    print("  → 超时控制：llm 配置 timeout=10s（真实请求见幕3的 BAD_LLM 配置）\n")

    print("=" * 60)
    print("幕2｜熔断三态：closed → open（快速失败）→ half_open（试探恢复）")
    breaker = CircuitBreaker(failure_threshold=3, recovery_time=1.5)

    @with_retry(retries=0, breaker=breaker)  # 不重试，专注观察熔断
    def failing() -> str:
        raise ConnectionError("上游服务挂了（模拟）")

    for i in range(1, 5):
        t0 = time.time()
        try:
            failing()
        except Exception as e:
            dt = time.time() - t0
            is_fast_fail = "熔断已打开" in str(e)
            print(f"  · 第{i}次调用：{e!s}（{dt * 1000:.0f}ms）" + (" ← 熔断打开，几乎零耗时" if is_fast_fail else ""))
    print(f"  → 熔断状态：{breaker.state}（连续失败≥3 → open）")
    print("  等待恢复期 1.5s …")
    time.sleep(1.6)
    try:
        failing()
    except Exception as e:
        print(f"  · 恢复试探（half_open）：仍失败 → {e!s} → 状态 {breaker.state}")
    print()

    print("=" * 60)
    print("幕3｜真实系统故障注入：坏 key → 裸调用崩溃（稳定性层用 with_retry + 熔断在 llm 接缝兜底）")
    from functools import lru_cache

    from xiao_wen import graph_builder as base
    from xiao_wen import intent as intent_mod

    # monkeypatch：把意图识别模型的 LLM 换成坏 key（注入点 = intent._intent_model 懒构建工厂；
    # system.classify_intent → intent.classify 在调用时模块级懒查找该工厂，替换即生效；
    # 分类 prompt 由当前词汇表动态构建（_build_prompt(_intents())）；BAD_LLM 仍是刻意绕过接缝的故障模型）
    @lru_cache
    def _bad_intent_model():
        return intent_mod._build_prompt(intent_mod._intents()) | BAD_LLM.with_structured_output(
            intent_mod.Intent, method="json_mode"
        )

    intent_mod._intent_model = _bad_intent_model
    state = {"user_input": "10月8日去北京开会4天", "recent": ""}

    print("  [A] 裸调用（无稳定性层）——预期：真实 LLM 请求失败（含内置重试 1 次 + 超时 10s）")
    t0 = time.time()
    try:
        base.classify_intent(dict(state))
        print("    · 竟然成功了？")
    except Exception as e:
        print(f"    · 抛异常：{type(e).__name__}: {str(e)[:70]}（{(time.time() - t0) * 1000:.0f}ms）")
        print("    · 真实系统里这就是一次崩溃：用户看到 traceback")

    print("=" * 60)
    print("幕4｜健康检查：系统自检")
    for row in health_check():
        print(f"  {row['状态']} {row['项']}：{row['详情']}")
    print("\n  完整日志见 data/stability.log")
