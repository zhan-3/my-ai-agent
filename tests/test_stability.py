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
    assert b.is_open is False  # 触发迁移：half_open 放行一个请求
    assert b.state == "half_open"
    b.record_success()  # 试探成功 → 复位
    assert b.state == "closed"
    assert b.failures == 0


def test_breaker_stays_open_on_recovery_failure():
    b = CircuitBreaker(failure_threshold=2, recovery_time=0.1)
    for _ in range(2):
        b.record_failure()
    time.sleep(0.15)
    b.record_failure()  # half_open 试探失败 → 立刻回 open
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
    assert calls["n"] == 3  # 第 1、2 次失败，第 3 次成功


def test_with_retry_gives_up_after_exhaustion():
    @with_retry(retries=2, base_delay=0.01)
    def always_fail():
        raise ValueError("持续失败")

    try:
        always_fail()
        raise AssertionError("应当抛异常")  # 走到这里说明逻辑不该放行
    except ValueError:
        pass


def test_with_retry_respects_breaker_open():
    b = CircuitBreaker(failure_threshold=1, recovery_time=60)
    b.record_failure()  # 打开

    @with_retry(retries=3, base_delay=0.01, breaker=b)
    def fn():
        return "不该走到这里"

    try:
        fn()
        raise AssertionError("熔断打开时应快速失败")  # 走到这里说明熔断未生效
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


def test_health_check_memory_backend_ready(monkeypatch):
    """Postgres 可连时健康检查报告记忆存储 = ✅（唯一后端 Postgres）"""
    import os

    from xiao_wen import memory as memory_mod
    from xiao_wen import stability as st

    monkeypatch.setenv(
        "POSTGRES_URL", os.environ.get("POSTGRES_TEST_URL", "postgresql://postgres:123456@localhost:5432/xiao_wen_test")
    )
    memory_mod._backend = None
    try:
        report = st.health_check()
        mem_item = next(i for i in report if i["项"] == "记忆存储")
        assert mem_item["状态"] == "✅"
        assert "Postgres" in mem_item["详情"]
    finally:
        memory_mod._backend = None


def test_health_check_memory_backend_missing_url_warns(monkeypatch):
    """未配 POSTGRES_URL → 记忆存储 = ⚠️（无内存兜底，探活不崩溃）
    注：health_check 内部 load_dotenv 会从 .env 补回环境变量，这里 patch 掉以测真实缺配场景"""
    import dotenv

    from xiao_wen import memory as memory_mod
    from xiao_wen import stability as st

    monkeypatch.setattr(dotenv, "load_dotenv", lambda: None)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    memory_mod._backend = None
    try:
        report = st.health_check()
        mem_item = next(i for i in report if i["项"] == "记忆存储")
        assert mem_item["状态"] == "⚠️"
        assert "POSTGRES_URL" in mem_item["详情"]
    finally:
        memory_mod._backend = None


def test_health_check_env_report_keys_follow_seam(monkeypatch):
    """环境配置项覆盖 llm 接缝的 REQUIRED_ENV_VARS + embedding 变量（单一来源）"""
    from xiao_wen import llm as llm_seam
    from xiao_wen import stability as st
    from xiao_wen.rag import _EMBED_ENV_VAR

    report = st.health_check()
    row = next(r for r in report if r["项"] == "环境配置")
    for v in llm_seam.REQUIRED_ENV_VARS:
        assert v in row["详情"]
    assert _EMBED_ENV_VAR in row["详情"]
