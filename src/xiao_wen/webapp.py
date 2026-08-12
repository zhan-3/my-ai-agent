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
- 会话隔离暂缓：session_id 预留，记忆为全局单文件（ADR-0002）
"""

import os

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from xiao_wen.session import chat as run_chat  # 会话循环收口（默认 = 图工厂调度图，多意图并行）

app = FastAPI(title="晓问 · 差旅出行助手", description="多 Agent 差旅助手 Web 界面")


class ChatRequest(BaseModel):
    user_input: str
    session_id: str = "default"  # 会话隔离（演示级内存；真实产品换 Redis）


class ChatResponse(BaseModel):
    answer: str
    intent: str
    reason: str


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """前端页面（单文件 HTML，无外部 CDN，离线可用）"""
    with open(HTML_PATH, encoding="utf-8") as f:
        return f.read()


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """聊天接口：完整走一遍主管图（含两层记忆闭环）"""
    text = req.user_input.strip()
    if not text:
        raise HTTPException(status_code=400, detail="输入不能为空")
    try:
        r = run_chat(text, req.session_id)
        return ChatResponse(answer=r.answer, intent=r.intent, reason=r.reason)
    except Exception as e:
        from xiao_wen.stability import logger

        logger.error("chat 失败（session=%s）：%s", req.session_id, e)
        return ChatResponse(answer="⚠️ 服务暂时不可用，请稍后再试。", intent="error", reason=str(e)[:120])


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
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
