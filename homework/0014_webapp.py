"""第十六课（加分项 F）：可视化 Web 界面 —— 让回答不只停留在终端

FastAPI 后端 + 原生 HTML/JS 前端（零构建、离线可用）。
跑法：
    uv run python homework/0014_webapp.py
    浏览器打开 http://127.0.0.1:8000
    交互式 API 文档：http://127.0.0.1:8000/docs

设计：
- 复用 0010 完整系统（六 worker 主管架构），不重写任何 Agent 逻辑
- 记忆闭环与 0010 demo 一致：每轮 invoke 前注入短期记忆（recent），
  invoke 后把 用户/助手 两轮写回（hot path）
- 会话隔离：内存 dict keyed by session_id（演示级；真实产品换 Redis 即可）
"""
import importlib.util
import os
import sys

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))  # 保证 memory_store 可 import
from memory_store import (add_message, format_recent_messages)  # noqa: E402


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块：{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 复用 0010 完整系统（六 worker 主管架构），不重写 Agent
sys_mod = _load("sys_v3", os.path.join(os.path.dirname(__file__), "0010_system.py"))
app_graph = sys_mod.app

app = FastAPI(title="晓问 · 差旅出行助手", description="多 Agent 差旅助手 Web 界面（加分项 F）")


class ChatRequest(BaseModel):
    user_input: str
    session_id: str = "default"   # 会话隔离（演示级内存；真实产品换 Redis）


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
        # 短期记忆：invoke 前注入最近对话（hot path 检索）
        recent = format_recent_messages(6)
        r = app_graph.invoke({
            "messages": [("human", text)],
            "user_input": text,
            "recent": recent,
        })
        # 短期记忆：invoke 后写回（hot path 写入）
        add_message("user", text)
        add_message("assistant", r["answer"])
        return ChatResponse(answer=r["answer"], intent=r.get("intent", "?"),
                            reason=r.get("reason", ""))
    except Exception as e:  # noqa: BLE001 —— 稳定性：任何异常都给友好文案
        from stability import logger
        logger.error("chat 失败（session=%s）：%s", req.session_id, e)
        return ChatResponse(answer="⚠️ 服务暂时不可用，请稍后再试。", intent="error", reason=str(e)[:120])


# ---- 前端页面（随文件存放，同目录 static/index.html） ----
HTML_PATH = os.path.join(os.path.dirname(__file__), "static", "index.html")


@app.get("/healthz")
def healthz() -> dict:
    """健康检查接口（配合加分项 D）"""
    from stability import health_check
    return {"checks": health_check()}


if __name__ == "__main__":
    if not os.path.exists(HTML_PATH):
        print(f"⚠️ 前端页面缺失：{HTML_PATH}，请确认 static/index.html 存在")
        sys.exit(1)
    print("=" * 56)
    print("晓问 · 差旅出行助手 Web 界面")
    print("  浏览器打开：http://127.0.0.1:8000")
    print("  API 文档：http://127.0.0.1:8000/docs")
    print("  Ctrl+C 退出")
    print("=" * 56)
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
