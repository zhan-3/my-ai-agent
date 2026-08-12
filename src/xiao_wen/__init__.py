"""晓问 · 智能出行助手 Agent（企业差旅多 Agent 系统）

基于 LangGraph 的「主管-工人」多 Agent 架构：意图识别主管 + 六个专职 Worker
（行程规划 / 偏好记录 / 历史查询 / 知识问答 / 联网查询 / 其他兜底），
配套两层记忆（短期对话 + 长期偏好/历史）、插件化注册中心、稳定性层与 Web 界面。

模块划分（正式命名）：
- memory            两层记忆存储（短期消息 + 长期偏好/行程，JSON 持久化）
- rag               知识问答（dashscope embedding + Chroma 向量检索）
- web               联网查询（ToolNode ReAct：天气/汇率/空气质量）
- system            完整系统总装（六 Worker 主管图，主入口）
- scheduler         调度优化（Send API fan-out/fan-in 并行执行）
- plugin_registry   插件注册中心（动态发现 / AST 渐进披露 / 懒加载）
- stability         稳定性层（重试 / 熔断 / 兜底 / 日志 / 健康检查）
- webapp            可视化 Web 界面（FastAPI）
- demos             演示脚本（plugin_demo / stability_demo）
"""

__version__ = "0.1.0"
