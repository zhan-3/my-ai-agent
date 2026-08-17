"""Web 界面模块：FastAPI 后端 + React 构建产物。
跑法：
    uv run python -m xiao_wen.webapp
    浏览器打开 http://127.0.0.1:8000
    交互式 API 文档：http://127.0.0.1:8000/docs
    （也可用 `uv run xiao-wen` 等价启动）

设计：
- 复用图工厂（graph_builder）调度图（子 Agent 注册表驱动主管架构，多意图并行），不重写任何 Agent 逻辑
- 记忆闭环收口于 xiao_wen.session.chat（读 recent → 注入 → invoke → 写回两轮）
- 异常兜底在 web 层（session 层向上抛）：任何异常给友好降级文案
- 认证与线程（ADR-0007/0009）：JWT 用户名决定长期记忆所有者；客户端 conversation_id
  只决定该用户作用域内的可见对话线程
"""

import json
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from xiao_wen import auth
from xiao_wen.config import load_settings
from xiao_wen.contract import (
    HistoryResult,
    Itinerary,
    KnowledgeSource,
    MemorySnapshot,
    Preference,
    TravelStats,
    TripPlan,
)
from xiao_wen.session import chat as run_chat  # 会话循环收口（默认 = 图工厂调度图，多意图并行）
from xiao_wen.session import service_error_event, stream_chat  # 流式会话循环（SSE 阶段事件）


@asynccontextmanager
async def _lifespan(_: FastAPI):
    load_settings().validate_web()
    yield


app = FastAPI(title="晓问 · 差旅出行助手", description="多 Agent 差旅助手 Web 界面", lifespan=_lifespan)


class AuthRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    user_input: str
    conversation_id: str = "default"


class ChatResponse(BaseModel):
    answer: str
    intent: str
    reason: str
    plan: TripPlan | None = None  # 结构化行程（契约 TripPlan，OpenAPI 自动出 schema）；非行程/结构不符为 None
    stats: TravelStats | None = None  # 差旅画像（契约 TravelStats）；非统计/结构不符为 None
    history: HistoryResult | None = None  # 历史查询结构化行程（契约 HistoryResult）；非历史查询为 None
    sources: list[KnowledgeSource] = []  # RAG 证据来源
    policy_status: str | None = None


class AuthResponse(BaseModel):
    token: str
    username: str


def _observed_chat(text: str, user: str, thread_id: str):
    from xiao_wen.observability import start_turn

    observer = start_turn(text, thread_id)
    if observer is None:
        return run_chat(text, thread_id, user_id=user)
    from xiao_wen.graph_builder import build_supervisor_graph

    try:
        graph = build_supervisor_graph(recorder=observer.recorder)
        return run_chat(text, thread_id, user_id=user, graph=graph, recorder=observer.recorder)
    except Exception as error:
        observer.recorder.record({"type": "error", "code": "unhandled", "message": str(error)})
        raise
    finally:
        observer.finish()


async def _observed_stream(text: str, user: str, thread_id: str):
    from xiao_wen.observability import start_turn

    observer = start_turn(text, thread_id)
    if observer is None:
        async for event in stream_chat(text, thread_id, user_id=user):
            yield event
        return
    from xiao_wen.graph_builder import build_supervisor_graph

    try:
        graph = build_supervisor_graph(recorder=observer.recorder)
        async for event in stream_chat(
            text,
            thread_id,
            user_id=user,
            graph=graph,
            recorder=observer.recorder,
        ):
            yield event
    except Exception as error:
        observer.recorder.record({"type": "error", "code": "unhandled", "message": str(error)})
        raise
    finally:
        observer.finish()


def _current_user(authorization: str | None = None) -> str:
    """从 Authorization: Bearer <token> 解出长期记忆所有者。

    FastAPI 依赖注入没法依赖 Header 条件参数，这里直接手动解析（统一 401 语义）。
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    user = auth.authenticate(authorization.removeprefix("Bearer ").strip())
    if user is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return user


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, authorization: str | None = Header(default=None)) -> ChatResponse:
    """聊天接口：JWT 决定用户，conversation_id 决定该用户内的可见线程。"""
    user = _current_user(authorization)
    from xiao_wen.dialogue import make_thread_id

    try:
        thread_id = make_thread_id(user, req.conversation_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    text = req.user_input.strip()
    if not text:
        raise HTTPException(status_code=400, detail="输入不能为空")
    try:
        r = _observed_chat(text, user, thread_id)
    except Exception as e:
        from xiao_wen.stability import logger

        logger.error("chat 失败（user=%s）：%s", user, e)
        raise HTTPException(
            status_code=503,
            detail={"code": "service_unavailable", "message": "⚠️ 服务暂时不可用，请稍后再试。", "retryable": True},
        ) from e
    failure = getattr(r, "failure", None)
    if failure is not None:
        raise HTTPException(status_code=503, detail=failure.__dict__)
    return ChatResponse(
        answer=r.answer,
        intent=r.intent,
        reason=r.reason,
        plan=getattr(r, "plan", None),
        stats=getattr(r, "stats", None),
        history=getattr(r, "history", None),
        sources=getattr(r, "sources", []),
        policy_status=getattr(r, "policy_status", None),
    )


def _sse(event: dict) -> str:
    """SSE 帧：单行 JSON data（前端按 \n\n 分帧）"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest, authorization: str | None = Header(default=None)) -> StreamingResponse:
    """SSE 流式聊天：阶段事件（意图识别/子 Agent 进度）+ 最终 done（answer/intent/reason/plan）。
    旧前端 / 旧契约走 /api/chat 不受影响；阶段事件让长 LLM 等待有实时进度反馈。
    """
    user = _current_user(authorization)
    from xiao_wen.dialogue import make_thread_id

    try:
        thread_id = make_thread_id(user, req.conversation_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    text = req.user_input.strip()
    if not text:
        raise HTTPException(status_code=400, detail="输入不能为空")

    async def gen():
        try:
            async for ev in _observed_stream(text, user, thread_id):
                yield _sse(ev)
        except Exception as e:  # 防御：任何未消化异常也转成 error 事件，客户端永不悬挂
            from xiao_wen.stability import logger

            logger.error("chat/stream 失败（user=%s）：%s", user, e)
            yield _sse(service_error_event())

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---- 认证端点（JWT，ADR-0007） ----
@app.post("/api/auth/register", response_model=AuthResponse)
def register(req: AuthRequest) -> AuthResponse:
    """注册并直接登录（返回 token）；用户名冲突 409"""
    token = auth.register(req.username, req.password)
    if token is None:
        if not req.username.strip() or not req.password:
            raise HTTPException(status_code=400, detail="用户名/密码不能为空")
        raise HTTPException(status_code=409, detail="用户名已存在")
    return AuthResponse(token=token, username=req.username.strip())


@app.post("/api/auth/login", response_model=AuthResponse)
def login(req: AuthRequest) -> AuthResponse:
    """登录：返回 token；用户名/密码错误 401"""
    token = auth.login(req.username, req.password)
    if token is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return AuthResponse(token=token, username=req.username.strip())


@app.get("/api/auth/me")
def me(authorization: str | None = Header(default=None)) -> dict:
    """校验当前 token → 返回用户名（前端登录态校验用）"""
    return {"username": _current_user(authorization)}


@app.get("/api/stats", response_model=TravelStats)
def stats(authorization: str | None = Header(default=None)) -> TravelStats:
    """当前用户差旅画像（确定性聚合，零 LLM）：次数/天数/常去城市/年度趋势。

    页面直接拉取渲染，不经 LLM——差旅统计是结构化数据查询，不是开放生成。
    """
    user = _current_user(authorization)
    from xiao_wen.stats import compute

    return TravelStats(**compute(user))


@app.get("/api/memory", response_model=MemorySnapshot)
def memory(authorization: str | None = Header(default=None)) -> MemorySnapshot:
    """当前用户记忆快照：偏好 + 历史行程（前端记忆侧栏可视化，体现 Agent 长期记忆）"""
    user = _current_user(authorization)
    from xiao_wen.memory import get_itineraries, get_preferences

    return MemorySnapshot(
        preferences=[Preference(**p) for p in get_preferences(session_id=user)],
        itineraries=[Itinerary(**it) for it in get_itineraries(session_id=user)],
    )


# ---- React 前端（frontend/dist 构建产物；开发模式走 vite dev :5173，/api 代理到本服务） ----
DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "dist")

_FRONTEND_HINT = """<!doctype html><meta charset="utf-8"><title>晓问 · 差旅出行助手</title>
<h3>晓问前端未构建</h3>
<p>请先执行：<code>cd frontend && pnpm build</code>，再刷新本页。</p>
<p>开发模式：<code>cd frontend && pnpm dev</code> → http://127.0.0.1:5173（/api 自动代理到本服务）</p>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """React 前端入口：frontend/dist 构建产物；未构建时给出构建指引"""
    html = os.path.join(DIST, "index.html")
    if os.path.exists(html):
        with open(html, encoding="utf-8") as f:
            return f.read()
    return _FRONTEND_HINT


@app.get("/livez")
def livez() -> dict:
    """进程存活探针：不访问 LLM、Embedding、数据库或磁盘运行时状态。"""
    return {"status": "alive"}


@app.get("/readyz")
def readyz() -> JSONResponse:
    """只读就绪探针：配置、Postgres、RAG 语料和前端静态资产。"""
    from xiao_wen.readiness import check_readiness

    report = check_readiness()
    return JSONResponse(status_code=200 if report.ready else 503, content=report.as_dict())


@app.get("/healthz")
def healthz() -> JSONResponse:
    """兼容旧部署入口；语义与 readiness 一致，不再无条件返回 200。"""
    return readyz()


if os.path.isdir(DIST):
    # 静态资源（assets/、favicon.svg、icons.svg）：构建产物存在时挂载（须在所有 API 路由之后注册）
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")


def main() -> None:
    """启动 Web 服务（控制台入口）"""
    if not os.path.isdir(DIST):
        print("ℹ️ React 前端未构建（frontend/dist 不存在）：")
        print("   - 访问 http://127.0.0.1:8000：先 cd frontend && pnpm build")
        print("   - 开发模式：cd frontend && pnpm dev（http://127.0.0.1:5173，/api 代理到本服务）")
    print("=" * 56)
    print("晓问 · 差旅出行助手 Web 界面")
    print("  浏览器打开：http://127.0.0.1:8000")
    print("  API 文档：http://127.0.0.1:8000/docs")
    print("  Ctrl+C 退出")
    print("=" * 56)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
