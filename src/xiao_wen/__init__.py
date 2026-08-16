"""晓问 · 智能出行助手 Agent（企业差旅多 Agent 系统）

基于 LangGraph 的「主管-子 Agent」多 Agent 架构：意图识别主管（词汇表 = 注册表
manifest 动态生成）+ 六个内置子 Agent（src/xiao_wen/agents/，可动态发现实体）
+ 外部扩展（plugins/，动态并入），配套两层记忆（短期对话 + 长期偏好/历史）、
子 Agent 注册中心、稳定性层与 Web 界面。

模块划分（正式命名）：
- llm               模型单一接缝（懒构造 + 校验 + 熔断守卫，ADR-0001）
- memory            两层记忆存储（短期消息 + 长期偏好/行程，唯一后端 Postgres）
- reference_data    领域参考数据单一来源（城市/车次/城市分级/住宿标准）
- rag               知识问答（dashscope embedding + Chroma 向量检索）
- web               联网查询（ToolNode ReAct：天气/汇率/空气质量）
- intent            意图识别单一来源（词汇表动态生成 + 多意图拆分，C3）
- trip_planner      行程规划管线（提取→补全→缺项→生成→写回，ADR-0003）
- agents            内置子 Agent 实体包（INTENT/DESCRIPTION/run，注册表扫描）
- plugin_registry   子 Agent 注册中心（动态发现 / AST 渐进披露 / 懒加载）
- stability         稳定性层（重试 / 熔断 / 日志 / 健康检查）
- session           会话循环收口（读最近对话 → 注入 → invoke → 写回两轮，ADR-0002）
- webapp            可视化 Web 界面（FastAPI）
- demos             演示脚本（plugin_demo / stability_demo / chat_demo）
"""

__version__ = "0.1.0"

# 项目根目录（src/xiao_wen/ 上溯两级 → 项目根；各模块共用，C7 收敛单一来源）
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
