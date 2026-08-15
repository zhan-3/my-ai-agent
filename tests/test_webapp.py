"""webapp 认证端点测试（TestClient，无 LLM 无 DB）

切片② 决策（Q4 定案）：认证后会话维度 = 用户身份——/api/chat 从
Authorization Bearer 解出用户名作为 session_id，客户端不再自填。
"""

from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from xiao_wen import auth, webapp


@pytest.fixture()
def client():
    # 隔离：用户存储走真实 Postgres（conftest autouse 已清 users 表 + 统一注入测试库 URL）
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


class TestMemoryEndpoint:
    """/api/memory：认证后返回当前用户偏好 + 历史行程（前端记忆侧栏数据源）"""

    def test_memory_requires_auth(self, client):
        assert client.get("/api/memory").status_code == 401

    def test_memory_returns_preferences_and_itineraries(self, client):
        from xiao_wen import memory as memory_store

        r = client.post("/api/auth/register", json={"username": "zhang", "password": "pass123"})
        token = r.json()["token"]
        # 当前用户写一条偏好 + 一条行程
        memory_store.add_or_update_preference("住宿", "喜欢住汉庭", session_id="zhang")
        memory_store.add_itinerary({"to_city": "北京"}, "北京出差", session_id="zhang")
        r = client.get("/api/memory", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        data = r.json()
        assert data["preferences"][0]["category"] == "住宿"
        assert data["preferences"][0]["content"] == "喜欢住汉庭"
        assert data["itineraries"][0]["to_city"] == "北京"


class TestStatsEndpoint:
    """/api/stats：差旅画像（确定性聚合，零 LLM）——401 / 空数据 / 聚合正确"""

    def test_stats_requires_auth(self, client):
        assert client.get("/api/stats").status_code == 401

    def test_stats_empty(self, client):
        token = client.post("/api/auth/register", json={"username": "zhang", "password": "pass123"}).json()["token"]
        r = client.get("/api/stats", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        data = r.json()
        assert data["has_data"] is False
        assert data["trips"] == 0

    def test_stats_aggregates(self, client):
        from xiao_wen import memory as memory_store

        token = client.post("/api/auth/register", json={"username": "zhang", "password": "pass123"}).json()["token"]
        memory_store.add_itinerary(
            {"to_city": "北京", "start_date": "2026-03-10", "duration_days": 3},
            "北京出差",
            session_id="zhang",
        )
        memory_store.add_itinerary(
            {"to_city": "上海", "start_date": "2026-05-01", "duration_days": 2},
            "上海出差",
            session_id="zhang",
        )
        memory_store.add_itinerary(
            {"to_city": "北京", "start_date": "2025-11-20", "duration_days": 1},
            "北京",
            session_id="zhang",
        )
        r = client.get("/api/stats", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        data = r.json()
        assert data["has_data"] is True
        assert data["trips"] == 3
        assert data["total_days"] == 6
        assert data["avg_days"] == 2.0
        assert data["top_cities"][0] == {"city": "北京", "count": 2}
        assert data["years"] == [{"year": "2025", "count": 1}, {"year": "2026", "count": 2}]
        assert data["upcoming_trips"] == 0

    def test_stats_filters_upcoming(self, client):
        """时空语义：未来规划（start_date > 今天）不算「去过」——画像只统计已发生，
        upcoming_trips 单独诚实标注"""
        from xiao_wen import memory as memory_store

        token = client.post("/api/auth/register", json={"username": "zhang", "password": "pass123"}).json()["token"]
        memory_store.add_itinerary(
            {"to_city": "北京", "start_date": "2026-01-10", "duration_days": 2},
            "北京出差",
            session_id="zhang",
        )
        memory_store.add_itinerary(
            {"to_city": "杭州", "start_date": "2099-12-01", "duration_days": 4},
            "杭州规划",
            session_id="zhang",
        )
        r = client.get("/api/stats", headers={"Authorization": f"Bearer {token}"})
        data = r.json()
        assert data["has_data"] is True
        assert data["trips"] == 1  # 未来规划不计入
        assert data["total_days"] == 2
        assert data["top_cities"] == [{"city": "北京", "count": 1}]
        assert data["upcoming_trips"] == 1  # 单独标注


class TestChatAuthEnforced:
    def test_chat_without_token_401(self, client):
        r = client.post("/api/chat", json={"user_input": "你好"})
        assert r.status_code == 401

    def test_chat_with_invalid_token_401(self, client):
        r = client.post("/api/chat", json={"user_input": "你好"}, headers={"Authorization": "Bearer junk"})
        assert r.status_code == 401

    def test_chat_stream_requires_auth(self, client):
        r = client.post("/api/chat/stream", json={"user_input": "你好"})
        assert r.status_code == 401


def test_chat_returns_structured_history(client, monkeypatch):
    """历史查询产出 history → /api/chat 响应带 history；非历史查询 → None"""
    history = {
        "itineraries": [
            {
                "start_date": "2026-05-08",
                "from_city": "上海",
                "to_city": "北京",
                "duration_days": 4,
                "summary": "北京出差",
                "status": "历史",
            }
        ],
        "preferences": [],
        "direction": "历史",
    }

    class HistResult:
        answer = "🗂️ 历史行程：…"
        intent = "历史查询"
        reason = "r"
        history: ClassVar[dict] = {}

    HistResult.history = history
    monkeypatch.setattr(webapp, "run_chat", lambda text, session_id: HistResult())
    token = client.post("/api/auth/register", json={"username": "li", "password": "pass123"}).json()["token"]
    r = client.post(
        "/api/chat",
        json={"user_input": "我上次的行程是什么"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["history"] == history
    assert body["history"]["itineraries"][0]["status"] == "历史"

    class PlainResult:
        answer = "政策标准如下"
        intent = "知识问答"
        reason = "r"

    monkeypatch.setattr(webapp, "run_chat", lambda text, session_id: PlainResult())
    r2 = client.post(
        "/api/chat",
        json={"user_input": "住宿标准是什么"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200
    assert r2.json()["history"] is None, "非历史查询不应带 history"

    def test_chat_stream_returns_sse_events(self, client, monkeypatch):
        """SSE：POST /api/chat/stream → text/event-stream，data 行含阶段事件 + done"""

        async def fake_stream(text, session_id):
            yield {"type": "stage", "status": "start"}
            yield {"type": "stage", "status": "working", "intent": "行程规划"}
            yield {"type": "stage", "status": "done", "intent": "行程规划"}
            yield {"type": "done", "answer": "行程如下", "intent": "行程规划", "reason": "r", "plan": None}

        monkeypatch.setattr(webapp, "stream_chat", fake_stream)
        token = client.post("/api/auth/register", json={"username": "zhang", "password": "pass123"}).json()["token"]
        r = client.post(
            "/api/chat/stream",
            json={"user_input": "10月8日去北京开会4天"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = r.text
        assert 'data: {"type": "stage"' in body
        assert '"intent": "行程规划"' in body
        assert '"type": "done"' in body and '"answer": "行程如下"' in body
        assert "\n\n" in body  # SSE 帧分隔

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

    def test_chat_returns_structured_plan(self, client, monkeypatch):
        """slice 1：run_chat 产出 plan → /api/chat 响应带 plan；无 plan → None（非行程）"""
        plan = {"summary": "北京出差", "days": [], "reasons": [], "date_is_vague": False}

        class FakeResult:
            answer = "行程如下"
            intent = "行程规划"
            reason = "r"
            plan: ClassVar[dict] = {}  # 类型占位：真实 plan 后置覆盖（类体里查不到外层局部变量）

        FakeResult.plan = plan
        monkeypatch.setattr(webapp, "run_chat", lambda text, session_id: FakeResult())
        token = client.post("/api/auth/register", json={"username": "zhang", "password": "pass123"}).json()["token"]
        r = client.post(
            "/api/chat",
            json={"user_input": "10月8日去北京开会4天"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["plan"] == plan

        class PlainResult:
            answer = "标准如下"
            intent = "知识问答"
            reason = "r"

        monkeypatch.setattr(webapp, "run_chat", lambda text, session_id: PlainResult())
        r2 = client.post(
            "/api/chat",
            json={"user_input": "差旅标准"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 200 and r2.json()["plan"] is None

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


class TestFrontendServing:
    """旧单文件 index.html 退役后：GET / 服务 React 构建产物（frontend/dist）；未构建给指引"""

    def test_index_hints_when_frontend_not_built(self, client, monkeypatch):
        monkeypatch.setattr(webapp, "DIST", "/nonexistent/dist")
        r = client.get("/")
        assert r.status_code == 200
        assert "pnpm build" in r.text and "晓问前端未构建" in r.text

    def test_index_serves_built_frontend(self, client, monkeypatch, tmp_path):
        (tmp_path / "index.html").write_text("<div id=root>晓问 React 前端</div>", encoding="utf-8")
        monkeypatch.setattr(webapp, "DIST", str(tmp_path))
        r = client.get("/")
        assert r.status_code == 200
        assert "<div id=root>晓问 React 前端</div>" in r.text


class TestChatStreamErrorPath:
    """SSE 错误路径：端点防御层（stream_chat 未消化异常 → error 帧，客户端永不悬挂）"""

    def test_chat_stream_midstream_error_still_sse_error_frame(self, client, monkeypatch):
        async def boom_stream(text, session_id):
            yield {"type": "stage", "status": "start"}
            raise RuntimeError("stream 内部炸了")

        monkeypatch.setattr(webapp, "stream_chat", boom_stream)
        token = client.post("/api/auth/register", json={"username": "zhang", "password": "pass123"}).json()["token"]
        r = client.post(
            "/api/chat/stream",
            json={"user_input": "你好"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert '"type": "error"' in r.text and "稍后再试" in r.text
        assert '"type": "done"' not in r.text
