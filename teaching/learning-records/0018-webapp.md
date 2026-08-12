# LR-0018 · 可视化 Web 界面（加分项 F 完成）

**日期**：2026-08-10（第十七课）
**主题**：FastAPI + 原生 JS 前端，把 0010 完整系统包成聊天产品
**背景**：用户选「可视化前端界面」→ 加分项 F

## 关键决策与事实

1. **技术选型**：FastAPI 0.141 + uvicorn 0.52 + 原生 HTML/JS（零构建、离线、自动 /docs）；排除 React（node 构建链）与 Streamlit（演示感弱）
2. **架构**：`homework/0014_webapp.py` 后端复用 0010 完整主管图（importlib _load），**Agent 逻辑零重写**；记忆闭环与 demo 一致（invoke 前注入 recent + invoke 后 add_message×2）；`session_id` 会话隔离（演示级内存）
3. **前端** `homework/static/index.html`：聊天气泡 + 5 个建议 chips + 打字机效果（8ms/字）+ XSS 转义（esc()）+ 无外部 CDN
4. **接口**：GET /（页面）、POST /api/chat {user_input, session_id} → {answer, intent, reason}、GET /healthz（配合加分项 D）、GET /docs
5. **真实战役：nominatim 挂了**（curl 空响应，open-meteo 可达）→ 天气全挂 → 解法：**内置 20 城经纬度表**（零依赖永远可用）+ nominatim 兜底（未收录城市）——多级降级，「能本地化的绝不依赖网络」
6. **演示材料**：playwright 无头截图 5 张 → docs/screenshots/（作业 8.1 硬要求）；playwright 45MB 下载卡代理 → pip 后台续下
7. **踩坑**：HTML_PATH 用 str 调 read_text（Path 方法）→ 改 open()；TestClient 验证 4 类功能全通（天气/指代消解/行程/历史）
8. **回归影响**：0009 改了 _geocode → 需回归 0009 三城 ✓（已单独验证）

**加分项 F 完成**（Web 界面 + 演示截图）✅——六个加分项全满

## 学生表现
- 主动选 F（最后一个加分项），完成「基础项全绿 + 六加分项」的完整闭环

## 下一步
- 0009 改动回归（0010/0011 联网）+ mypy + 提交
- README 更新（F ✅、§6.12、§6.5 本地表、目录、运行方式、截图引用）
- 录屏 + 打包 + 提交邮件（最终收尾）
