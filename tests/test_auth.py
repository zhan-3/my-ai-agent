"""认证模块测试（纯逻辑 + 真实 Postgres users 表）

决策集（grilling 默认 + bcrypt）：
- JWT 无状态认证（pyjwt，HS256）；用户存储唯一后端 Postgres users 表
- bcrypt 密码哈希（用户指定）；注册即登录（返回 token）
- 认证后会话维度 = 用户身份（webapp 层强制，见切片②）
"""

import os

import jwt
import pytest

from xiao_wen import auth
from xiao_wen.memory_pg import PostgresUserStore


def _fresh_store() -> PostgresUserStore:
    """真实 Postgres 用户存储（测试库；conftest 已清 users 表，这里再清一次保险）"""
    url = os.environ.get("POSTGRES_TEST_URL") or os.environ["POSTGRES_URL"]
    s = PostgresUserStore(url)
    s.clear_all()
    return s


class TestPasswordHashing:
    def test_hash_and_verify(self):
        h = auth.hash_password("s3cret")
        assert h != "s3cret" and h.startswith("$2")
        assert auth.verify_password("s3cret", h)
        assert not auth.verify_password("wrong", h)

    def test_salt_makes_hashes_differ(self):
        assert auth.hash_password("same") != auth.hash_password("same")


class TestToken:
    def test_create_and_decode_roundtrip(self):
        token = auth.create_token("张三", "test-secret")
        assert auth.decode_token(token, "test-secret") == "张三"

    def test_wrong_secret_rejected(self):
        token = auth.create_token("张三", "test-secret")
        assert auth.decode_token(token, "other-secret") is None

    def test_garbage_and_empty_rejected(self):
        assert auth.decode_token("not-a-jwt", "test-secret") is None
        assert auth.decode_token("", "test-secret") is None

    def test_expired_rejected(self):
        token = jwt.encode({"sub": "张三", "exp": 0}, "test-secret", algorithm="HS256")
        assert auth.decode_token(token, "test-secret") is None

    def test_configured_secret_is_not_frozen_at_import(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "a" * 32)
        token = auth.create_token("张三")
        monkeypatch.setenv("JWT_SECRET", "b" * 32)
        assert auth.decode_token(token) is None


class TestRegisterLogin:
    def test_register_creates_user_and_returns_token(self):
        store = _fresh_store()
        auth.set_user_store(store)
        try:
            token = auth.register("zhang", "pass123")
            assert token is not None
            # token 解出用户名
            assert auth.decode_token(token) == "zhang"
            # 存储的是哈希不是明文
            rec = store.get_user("zhang")
            assert rec is not None and rec["password_hash"] != "pass123"
        finally:
            auth._user_store = None

    def test_register_duplicate_returns_none(self):
        store = _fresh_store()
        auth.set_user_store(store)
        try:
            assert auth.register("zhang", "pass123") is not None
            assert auth.register("zhang", "other") is None
        finally:
            auth._user_store = None

    def test_login_success_and_failures(self):
        store = _fresh_store()
        auth.set_user_store(store)
        try:
            auth.register("zhang", "pass123")
            assert auth.login("zhang", "pass123") is not None
            assert auth.login("zhang", "wrong") is None
            assert auth.login("nobody", "pass123") is None
        finally:
            auth._user_store = None

    def test_authenticate_uses_current_secret(self):
        store = _fresh_store()
        auth.set_user_store(store)
        try:
            auth.register("zhang", "pass123")
            token = auth.login("zhang", "pass123")
            assert token is not None
            assert auth.authenticate(token) == "zhang"
            assert auth.authenticate("junk") is None
        finally:
            auth._user_store = None


class TestUserStoreConstraints:
    def test_get_user_store_requires_postgres_url(self, monkeypatch):
        """未配 POSTGRES_URL 时明确报错。"""
        monkeypatch.delenv("POSTGRES_URL", raising=False)
        monkeypatch.delenv("POSTGRES_TEST_URL", raising=False)
        auth._user_store = None
        try:
            with pytest.raises(RuntimeError, match="POSTGRES_URL"):
                auth._get_user_store()
        finally:
            auth._user_store = None


def test_postgres_user_store_crud():
    s = _fresh_store()
    assert s.register("u1", "h1") is not None
    assert s.register("u1", "h2") is None  # 用户名唯一
    rec = s.get_user("u1")
    assert rec is not None and rec["password_hash"] == "h1"
    assert s.get_user("nobody") is None
