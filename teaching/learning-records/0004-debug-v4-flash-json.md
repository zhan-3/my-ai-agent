# 定位并修复中转站 + DeepSeek v4 的间歇性 400 错误

用户手动测试发现间歇性报错（同一脚本第一句成功、第二句 400），要求代跑复现。完整排查链条。

## 复现
- 默认写法 `with_structured_output(Intent)` 第一句成功、第二句 400：`This response_format type is unavailable now`
- 不稳定原因推测：中转站多路负载，部分上游支持 json_schema，部分不支持（未经证实的推断，但解释了间歇性）

## 根因（用原始 OpenAI SDK 7 项对照实验锁定，模型 = deepseek-v4-flash）
1. **thinking 模式默认开启**（DeepSeek V4 特性，effort=high）
2. thinking 下 `response_format json_schema` 不可用 → 400 #1
3. thinking 下强制 `tool_choice`（function_calling 方式）不可用 → 400 #2（"Thinking mode does not support this tool_choice"）
4. `json_object` 模式可用，但**提示词必须含「json」字样**
5. `extra_body={"thinking": {"type": "disabled"}}` 能透传中转站（实验 6/7 证明）
6. langchain-openai 1.4.2 默认 method 已从 function_calling 改为 json_schema —— 版本升级是踩坑诱因

## 最终方案（homework/0003_intent.py 已固化）
- `ChatOpenAI(..., extra_body={"thinking": {"type": "disabled"}})` 关 thinking
- `llm.with_structured_output(Intent, method="json_mode")` 用 json_object
- 系统提示词写死英文键名 "intent"/"reason"（json_mode 只保证 JSON 不保证 schema 一致，模型曾输出中文键）
- 提示词模板中 JSON 示例花括号转义 `{{ }}`（否则 ChatPromptTemplate 当变量）
- 3/3 分类正确、多次重跑稳定

## 教学要点（已对用户传递）
- 调试方法：不做猜测，用原始 SDK 做能力边界对照实验（纯文本 / json_object / json_schema / tools-auto / tools-强制 / 关thinking 组合）
- with_structured_output 三种 method 的取舍：json_schema（严格，v4-flash 不支持）> function_calling（需非 thinking）> json_mode（宽松，靠提示词兜底）
- 中转站/模型的真实能力边界要用实验摸，不能只看文档

## 用户状态
- 用户主动做手动测试并发现间歇性问题（好习惯）；修复全程老师代做
- 下节课可教用户自己跑对照实验的方法
