"""稳定性层单元测试：熔断三态、重试退避、异常兜底（纯逻辑，无网络）"""
import time

from xiao_wen.stability import CircuitBreaker, safe_call, with_retry


def test_breaker_three_states():
    b = CircuitBreaker(failure_threshold=3, recovery_time=1.0)
    assert b.state == "closed"
    assert not b.is_open
    # 连续失败 3 次 → open
    for _ in range(3):
        b.record_failure()
    assert b.state == "open"
    assert b.is_open
    # open 期间快速拒绝
    assert b.is_open
    # 恢复期到 → 访问 is_open 触发 half_open 试探
    time.sleep(1.05)
    assert b.is_open is False       # 触发迁移：half_open 放行一个请求
    assert b.state == "half_open"
    b.record_success()              # 试探成功 → 复位
    assert b.state == "closed"
    assert b.failures == 0


def test_breaker_stays_open_on_recovery_failure():
    b = CircuitBreaker(failure_threshold=2, recovery_time=0.1)
    for _ in range(2):
        b.record_failure()
    time.sleep(0.15)
    b.record_failure()            # half_open 试探失败 → 立刻回 open
    assert b.state == "open"


def test_with_retry_succeeds_after_flaky_failures():
    calls = {"n": 0}

    @with_retry(retries=2, base_delay=0.01)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("闪断")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3        # 第 1、2 次失败，第 3 次成功


def test_with_retry_gives_up_after_exhaustion():
    @with_retry(retries=2, base_delay=0.01)
    def always_fail():
        raise ValueError("持续失败")

    try:
        always_fail()
        assert False, "应当抛异常"
    except ValueError:
        pass


def test_with_retry_respects_breaker_open():
    b = CircuitBreaker(failure_threshold=1, recovery_time=60)
    b.record_failure()            # 打开

    @with_retry(retries=3, base_delay=0.01, breaker=b)
    def fn():
        return "不该走到这里"

    try:
        fn()
        assert False, "熔断打开时应快速失败"
    except RuntimeError as e:
        assert "熔断已打开" in str(e)


def test_safe_call_returns_fallback():
    def boom():
        raise RuntimeError("崩了")

    out = safe_call(boom, "⚠️ 服务暂时不可用")
    assert out == "⚠️ 服务暂时不可用"

    def ok():
        return "正常"

    assert safe_call(ok, "fallback") == "正常"
