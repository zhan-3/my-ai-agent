"""Web 界面模块：FastAPI 后端 + 原生 HTML/JS 前端（零构建、离线可用）
跑法：
    uv run python -m xiao_wen.webapp
    浏览器打开 http://127.0.0.1:8000
    交互式 API 文档：http://127.0.0.1:8000/docs
    （也可用 `uv run xiao-wen` 等价启动）

设计：
- 复用图工厂（graph_builder）调度图（子 Agent 注册表驱动主管架构，多意图并行），不重写任何 Agent 逻辑
- 记忆闭环收口于 xiao_wen.session.chat（读 recent → 注入 → invoke → 写回两轮）
- 异常兜底在 web 层（session 层向上抛）：任何异常给友好降级文案
- 认证（ADR-0007）：JWT 无状态认证；会话维度 = 用户身份——/api/chat 从
  Authorization Bearer 解出用户名作为 session_id，客户端不再自填（用户隔离）
"""

import os

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from xiao_wen import auth
from xiao_wen.session import chat as run_chat  # 会话循环收口（默认 = 图工厂调度图，多意图并行）

app = FastAPI(title="晓问 · 差旅出行助手", description="多 Agent 差旅助手 Web 界面")


class AuthRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    user_input: str


class ChatResponse(BaseModel):
    answer: str
    intent: str
    reason: str


class AuthResponse(BaseModel):
    token: str
    username: str


def _current_user(authorization: str | None = None) -> str:
    """从 Authorization: Bearer <token> 解出用户名（会话维度 = 用户身份，Q4 定案）

    FastAPI 依赖注入没法依赖 Header 条件参数，这里直接手动解析（统一 401 语义）。
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    user = auth.authenticate(authorization.removeprefix("Bearer ").strip())
    if user is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return user


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """前端页面（单文件 HTML，无外部 CDN，离线可用）"""
    with open(HTML_PATH, encoding="utf-8") as f:
        return f.read()


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, authorization: str | None = Header(default=None)) -> ChatResponse:
    """聊天接口：完整走一遍主管图（含两层记忆闭环）；会话维度 = 登录用户（Q4 强制）"""
    user = _current_user(authorization)
    text = req.user_input.strip()
    if not text:
        raise HTTPException(status_code=400, detail="输入不能为空")
    try:
        r = run_chat(text, user)
        return ChatResponse(answer=r.answer, intent=r.intent, reason=r.reason)
    except Exception as e:
        from xiao_wen.stability import logger

        logger.error("chat 失败（user=%s）：%s", user, e)
        return ChatResponse(answer="⚠️ 服务暂时不可用，请稍后再试。", intent="error", reason=str(e)[:120])


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


@app.get("/api/memory")
def memory(authorization: str | None = Header(default=None)) -> dict:
    """当前用户记忆快照：偏好 + 历史行程（前端记忆侧栏可视化，体现 Agent 长期记忆）"""
    user = _current_user(authorization)
    from xiao_wen.memory import get_itineraries, get_preferences

    return {
        "preferences": get_preferences(session_id=user),
        "itineraries": get_itineraries(session_id=user),
    }


# ---- 前端页面（随文件存放，同目录 static/index.html） ----
HTML_PATH = os.path.join(os.path.dirname(__file__), "static", "index.html")


@app.get("/healthz")
def healthz() -> dict:
    """健康检查接口（配合稳定性自检）"""
    from xiao_wen.stability import health_check

    return {"checks": health_check()}


def main() -> None:
    """启动 Web 服务（控制台入口）"""
    if not os.path.exists(HTML_PATH):
        print(f"⚠️ 前端页面缺失：{HTML_PATH}，请确认 static/index.html 存在")
        raise SystemExit(1)
    print("=" * 56)
    print("晓问 · 差旅出行助手 Web 界面")
    print("  浏览器打开：http://127.0.0.1:8000")
    print("  API 文档：http://127.0.0.1:8000/docs")
    print("  Ctrl+C 退出")
    print("=" * 56)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
