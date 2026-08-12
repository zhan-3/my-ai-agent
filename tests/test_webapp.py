"""webapp 认证端点测试（TestClient，无 LLM 无 DB）

切片② 决策（Q4 定案）：认证后会话维度 = 用户身份——/api/chat 从
Authorization Bearer 解出用户名作为 session_id，客户端不再自填。
"""

import pytest
from fastapi.testclient import TestClient

from xiao_wen import auth, webapp


@pytest.fixture()
def client(monkeypatch):
    # 隔离：用户存储 + 记忆后端都用 InMemory（测试注入，复用同一实例保证注册/登录可见）
    auth.set_user_store(auth.InMemoryUserStore())
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    auth._user_store = None
    yield TestClient(webapp.app)
    auth._user_store = None


class TestRegisterLogin:
    def test_register_returns_token(self, client):
        r = client.post("/api/auth/register", json={"username": "zhang", "password": "pass123"})
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "zhang"
        assert auth.decode_token(data["token"], auth.JWT_SECRET) == "zhang"

    def test_register_duplicate_409(self, client):
        assert client.post("/api/auth/register", json={"username": "zhang", "password": "a"}).status_code == 200
        assert client.post("/api/auth/register", json={"username": "zhang", "password": "b"}).status_code == 409

    def test_register_empty_400(self, client):
        assert client.post("/api/auth/register", json={"username": "", "password": ""}).status_code == 400

    def test_login_ok_and_fail(self, client):
        client.post("/api/auth/register", json={"username": "zhang", "password": "pass123"})
        r = client.post("/api/auth/login", json={"username": "zhang", "password": "pass123"})
        assert r.status_code == 200 and r.json()["username"] == "zhang"
        r = client.post("/api/auth/login", json={"username": "zhang", "password": "wrong"})
        assert r.status_code == 401

    def test_me_with_and_without_token(self, client):
        r = client.post("/api/auth/register", json={"username": "zhang", "password": "pass123"})
        token = r.json()["token"]
        assert client.get("/api/auth/me").status_code == 401
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200 and r.json()["username"] == "zhang"


class TestChatAuthEnforced:
    def test_chat_without_token_401(self, client):
        r = client.post("/api/chat", json={"user_input": "你好"})
        assert r.status_code == 401

    def test_chat_with_invalid_token_401(self, client):
        r = client.post("/api/chat", json={"user_input": "你好"}, headers={"Authorization": "Bearer junk"})
        assert r.status_code == 401

    def test_chat_uses_user_as_session(self, client, monkeypatch):
        """强制用户隔离：run_chat 收到的 session_id == 用户名，忽略客户端自填"""
        calls = []

        class FakeResult:
            answer = "答"
            intent = "其他"
            reason = "r"

        def fake_run_chat(text, session_id):
            calls.append((text, session_id))
            return FakeResult()

        monkeypatch.setattr(webapp, "run_chat", fake_run_chat)
        r = client.post("/api/auth/register", json={"username": "zhang", "password": "pass123"})
        token = r.json()["token"]
        r = client.post(
            "/api/chat",
            json={"user_input": "你好", "session_id": "我不该自填"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert calls == [("你好", "zhang")]  # 客户端自填被忽略

    def test_two_users_isolated(self, client, monkeypatch):
        """用户 A/B 各自 token → 会话维度各自独立"""
        seen: dict[str, int] = {}

        class FakeResult:
            answer = "答"
            intent = "其他"
            reason = "r"

        def fake_run_chat(text, session_id):
            seen.setdefault(session_id, 0)
            seen[session_id] += 1
            return FakeResult()

        monkeypatch.setattr(webapp, "run_chat", fake_run_chat)
        ta = client.post("/api/auth/register", json={"username": "userA", "password": "a"}).json()["token"]
        tb = client.post("/api/auth/register", json={"username": "userB", "password": "b"}).json()["token"]
        for _ in range(2):
            client.post("/api/chat", json={"user_input": "hi"}, headers={"Authorization": f"Bearer {ta}"})
        client.post("/api/chat", json={"user_input": "hi"}, headers={"Authorization": f"Bearer {tb}"})
        assert seen == {"userA": 2, "userB": 1}
