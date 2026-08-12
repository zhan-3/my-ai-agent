"""认证模块测试（纯逻辑，无 LLM 无 DB）——切片① 红绿

决策集（grilling 默认 + bcrypt）：
- JWT 无状态认证（pyjwt，HS256）；用户存储 Postgres users 表 / InMemory 演示兜底
- bcrypt 密码哈希（用户指定）；注册即登录（返回 token）
- 认证后会话维度 = 用户身份（webapp 层强制，见切片②）
"""

import jwt

from xiao_wen import auth


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


class TestRegisterLogin:
    def test_register_creates_user_and_returns_token(self, monkeypatch):
        store = auth.InMemoryUserStore()
        monkeypatch.setattr(auth, "_get_user_store", lambda: store)
        token = auth.register("zhang", "pass123")
        assert token is not None
        # token 解出用户名
        assert auth.decode_token(token, auth.JWT_SECRET) == "zhang"
        # 存储的是哈希不是明文
        rec = store.get_user("zhang")
        assert rec is not None and rec["password_hash"] != "pass123"

    def test_register_duplicate_returns_none(self, monkeypatch):
        store = auth.InMemoryUserStore()
        monkeypatch.setattr(auth, "_get_user_store", lambda: store)
        assert auth.register("zhang", "pass123") is not None
        assert auth.register("zhang", "other") is None

    def test_login_success_and_failures(self, monkeypatch):
        store = auth.InMemoryUserStore()
        monkeypatch.setattr(auth, "_get_user_store", lambda: store)
        auth.register("zhang", "pass123")
        assert auth.login("zhang", "pass123") is not None
        assert auth.login("zhang", "wrong") is None
        assert auth.login("nobody", "pass123") is None

    def test_authenticate_uses_current_secret(self, monkeypatch):
        store = auth.InMemoryUserStore()
        monkeypatch.setattr(auth, "_get_user_store", lambda: store)
        auth.register("zhang", "pass123")
        token = auth.login("zhang", "pass123")
        assert token is not None
        assert auth.authenticate(token) == "zhang"
        assert auth.authenticate("junk") is None


class TestUserStoreDispatch:
    def test_env_postgres_dispatches_pg_store(self, monkeypatch):
        import importlib

        mpg = importlib.import_module("xiao_wen.memory_pg")
        calls = []

        class FakePG:
            def __init__(self, url: str):
                calls.append(url)

        monkeypatch.setattr(mpg, "PostgresUserStore", FakePG)
        monkeypatch.setenv("POSTGRES_URL", "postgresql://postgres:123456@localhost:5432/xiao_wen")
        auth._user_store = None
        auth._get_user_store()
        assert calls == ["postgresql://postgres:123456@localhost:5432/xiao_wen"]
        auth._user_store = None

    def test_no_env_uses_inmemory(self, monkeypatch):
        monkeypatch.delenv("POSTGRES_URL", raising=False)
        auth._user_store = None
        assert isinstance(auth._get_user_store(), auth.InMemoryUserStore)
        auth._user_store = None


def test_inmemory_user_store_crud():
    s = auth.InMemoryUserStore()
    assert s.register("u1", "h1") is not None
    assert s.register("u1", "h2") is None  # 用户名唯一
    rec = s.get_user("u1")
    assert rec is not None and rec["password_hash"] == "h1"
    assert s.get_user("nobody") is None
