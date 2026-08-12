# 意图识别节点全链路跑通（基础项 B 核心完成）

homework/0003_intent.py 端到端跑通：.env → load_dotenv → 中转站(OpenAI 兼容) → ChatOpenAI → with_structured_output → LangGraph 节点。3/3 分类正确。

## 关键技术点（用户已看到实证）
1. **中转站 = OpenAI 兼容**：ChatOpenAI(base_url, api_key, model) 一个类接入；DeepSeek 官方确认 OpenAI 格式 + 工具调用/JSON 支持
2. **环境变量方案**：用户先 export（仅终端会话可见，我的 shell 读不到）→ 迁移到 .env + python-dotenv；.env 已加入 .gitignore（安全）
3. **结构化输出**：with_structured_output(Intent schema)，模型直接返回 Pydantic 实例
4. **系统提示词决定分类质量**：无规则时「出差三天喜欢连锁酒店」被带偏成「其他」；加规则（主导意图优先）后 3/3 正确 —— 这是作业基础项 B 的核心难点实证
5. **Pylance 类型警告 ≠ 运行错误**：api_key 参数声明为 SecretStr；修法 from pydantic import SecretStr 包裹（另获防日志泄露收益）

## 用户状态
- 环境接线全部由老师代做（用户未自己写 0003 脚本，明确说「我还没开始写」）——动手任务执行率偏低，后续练习需要降门槛或换方式（如改一行 vs 写整段）
- 用户主动决策：export → .env（安全意识好）；遇到报错会贴错误信息（好习惯）

## 下一步（第四课）
- 意图识别接条件边 → 调度骨架：START → 意图识别节点 → 按 intent 路由到不同处理节点（先桩节点，再接行程规划主链路）
- 预告：行程规划 Agent（基础项 A）是价值核心，接 ToolNode（检索记忆/联网）
