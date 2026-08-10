# 差旅''晓问''——智能出行助手Agent

## 一、项目概述

### 1\.1 理解什么是Agent

在看本次作业前，大家需要先理解什么是Agent,它与传统大模型之间有什么区别

“Agent”和“豆包、DeepSeek 这类传统大模型”并不是同一个概念。豆包、DeepSeek 等常用大模型，本质上是提供语言理解、推理和生成能力的“模型底座”，像一个很强的“大脑”, 只输出文字告诉我们怎么做, 具体操作还是要靠我们自己；而 Agent 则是给大模型加上手脚,让它不但可以告诉我们怎么做, 还可以真正去执行那些文字里它让我们做的事，它在大模型基础上进一步加入任务拆解、流程控制、工具调用、记忆管理和结果汇总等能力构成一个“能思考可执行的系统”，是一个能够独立完成具体工作的“智能体”。简单来说，大模型更擅长“回答问题”，而 Agent 更强调“把一个复杂任务一步步完成”，例如先识别用户意图，再查询历史偏好、调用知识库或外部信息工具，最后生成完整结果。因此，本次作业的重点不只是接一个模型做对话，而是基于大模型能力，设计出一个真正能完成差旅任务的多 Agent 系统。

### 1\.2 项目背景

相信小伙伴们都有过做旅行规划的经历，传统旅行规划方式效率低、体验差，我们需要在多个平台查询景点、攻略、酒店、交通、天气等信息，规划一次行程往往需要花费2\-3小时。

此外，企业差旅场景还面临知识查询的难题——差旅政策、报销标准、预订流程等信息分散在各个文档中，用户难以快速获取准确答案，大模型直接回答又容易产生幻觉。

基于上述痛点，我们的第二次作业要开发一个基于多Agent架构的智能差旅出行助手，旨在为用户提供个性化、高效的行程规划服务。

### 1\.3 项目目标

你需要实现一个面向差旅场景的多 Agent 应用，尽量覆盖以下能力：

- 能理解用户自然语言需求，而不是只靠关键词匹配

- 能根据任务类型选择合适的子 Agent 执行

- 能保存并利用用户偏好、历史对话或历史行程

- 能接入企业知识库，回答差旅政策、报销标准、预订流程等问题

- 能在需要时查询实时或半实时信息，如天气、地点信息、交通限制等

- 能最终输出清晰、结构化、可读的行程建议或问答结果

---

## 二、核心问题

本次项目核心链路为：

`用户输入 -> 意图识别 Agent -> 调度 Agent -> 各子 Agent -> 汇总输出`

项目包含以下几个角色：

- `Intention Agent`
负责识别用户意图、抽取关键信息、决定后续调用哪些子 Agent

- `Orchestration Agent`
负责统一调度、串并行执行、结果汇总

- `Event Collection Agent`
负责提取出发地、目的地、时间、人数、预算、出行目的等行程要素

- `Preference Agent`
负责提取和更新用户偏好，如酒店、交通、餐饮、出行风格

- `Memory Query Agent`
负责查询历史对话、历史行程、历史偏好

- `Knowledge / RAG Agent`
负责企业差旅政策、报销规则、流程问答 
相关资料文档 \( 用于切片 \)  :

    **知识库内容**（8类文档）：

    - 差旅标准和规定

    - 报销政策

    - 预订指南

    - 常见问题FAQ

    - 紧急情况处理

    - 平台使用指南

    - 城市差旅指南

    - 环保倡议

[documents\.zip](图片和附件/documents.zip)

- `Information Query Agent`
负责联网或外部数据查询

- `Itinerary Planning Agent`
负责最终行程规划与结果生成

说明：

作业理想形态是**一个调度中枢带多个专职 Agent 协作完成任务, **不要把题目做成单一聊天机器人或单一问答机器人。

---

## 三、基础项与加分项

### 3\.1 基础项

#### 基础项 A：多 Agent 基本架构

至少实现 5 个以上可分工的 Agent，并体现出明确职责划分。

最低建议：

- `Intention Agent` 意图识别 Agent

- `Orchestration Agent`调度 Agent

- `Event Collection Agent` 要素提取Agent

- `Knowledge / RAG Agent`知识问答 Agent 

- `Itinerary Planning Agent`行程规划 Agent

#### 基础项 B：自然语言意图识别

系统应能够根据用户输入判断任务类型，例如：

- 行程规划

- 偏好记录或偏好更新

- 历史查询

- 知识问答

- 联网查询

要求：

- 应基于大模型语义理解实现

- 不建议仅使用关键词 if\-else 规则硬匹配

- 能提取关键信息，如时间、地点、预算、出行目的等

#### 基础项 C：行程规划主流程

系统应能完成一条完整主流程，例如：

用户说：

“我下周从北京去杭州出差三天，喜欢住连锁酒店，帮我安排一下行程。”

系统至少应做到：

- 识别这是“行程规划”任务

- 抽取出发地、目的地、时间、时长、偏好

- 调用对应子 Agent

- 生成较完整的行程结果

#### 基础项 D：基础记忆能力

至少实现一种可持续利用的记忆能力，例如：

- 记录用户偏好

- 记录最近几轮对话

- 在下一轮对话中能够引用历史信息

最低要求：

- 至少有短期上下文记忆, 当然有长期记忆存入数据库更好哈

- 用户前一轮提过的信息，下一轮能够继续使用

#### 基础项 E：结果可读性

输出结果要清晰，不要只返回一大段原始 JSON。

建议输出形式：

- 行程摘要

- 每日安排

- 安排理由\(例如 差旅政策、报销规则、交通拥堵、天气等\)

- 注意事项

- 缺失信息提示

- 参考来源或依据说明

---

### 3\.2 加分项

#### 加分项 A：两层记忆架构

在短期记忆基础上，实现长期记忆。

例如：

- 短期记忆：最近 N 轮对话

- 长期记忆：用户偏好、历史行程、常用目的地、出差习惯

如果还能实现“偏好追加/覆盖”的区分，可额外加分。

例如：

- “我喜欢住汉庭” 是新增偏好

- “我现在常住上海” 是更新长期信息, 下次用户直接说去哪不要再傻傻的问了

#### 加分项 B：调度优化

实现比“固定顺序串行执行”更好的调度方式。

例如：

- 优先级调度

- 同优先级任务并行执行

- 先收集信息，再触发规划 Agent

- 根据任务类型动态选择 Agent

#### 加分项 C：插件化、模块化架构

如果你的子 Agent 支持 动态发现机制，自动扫描注册、懒加载、渐进式披露，可加分。

例如：

- 未使用的模块不加载

- 渐进式暴露，意图识别阶段仅加载元数据

#### 加分项 D：工程稳定性

例如：

- LLM 调用失败重试

- 超时控制

- 熔断

- 异常兜底

- 日志记录

- 健康检查

#### 加分项 E：评测与测试

例如：

- 设计典型测试用例

- 对意图识别、记忆、RAG、规划效果进行验证

- 提供简单的自动化测试或回归测试

#### 加分项 F：可视化界面

例如：

- 可以写个访问的Web界面

- 产品化我们的项目, 让回答不只停留在终端

---

## 四、技术选型与推荐

### 4\.1 推荐语言

推荐优先使用 `Python`。

原因：

- Python 是当前 Agent 开发主流语言

- 生态成熟，文档多，样例多，开发效率高

- 更容易接入大模型、RAG、工具调用、工作流编排

### 4\.2 推荐框架

推荐使用以下方案之一：

#### 方案一：Python \+ LangChain \+ LangGraph\(最推荐\)

适合：

- 多 Agent 编排

- 状态流转

- 工具调用

- RAG 能力集成

#### 方案二：Python \+ 其他框架

也可以选用其他 Agent 框架或自行实现，只要结构合理即可。

例如：

- AutoGen

- CrewAI

- AgentScope

- LlamaIndex

- \.\.\.

#### 方案三：Java \+ Spring AI

如果同学更熟悉 Java，可使用：

- Java

- Spring AI

说明：

虽然语言和框架不做唯一限制，但Java不是开发Agent的主流, Python 才是 Agent 开发当之无愧的主流语言, 主流Agent框架如 LangChain、LangGraph、CrewAI、LlamaIndex 等，都是基于 Python 构建的, 如果你要使用最前沿的模型或工具，你几乎一定会遇到 Python 代码。

### 4\.3 模型选型建议

可接入任意合适的大模型 API，例如：

- 豆包

- DeepSeek

- 通义

- OpenAI 兼容接口模型

- 其他成本较低、效果可接受的大模型

建议优先选择：

- 成本可控

- 中文理解较好

- 结构化输出较稳定

- 支持工具调用, 至少支持稳定 JSON 输出

### 4\.4 存储与检索建议

可参考如下方案：

- 短期记忆： Redis缓存

- 长期记忆： PostgreSQL / MySQL 

- RAG 向量库：FAISS / Chroma / Milvus / pgvector

---

## 五、学习资源链接

目前 AI 在这一领域仍处于探索阶段，不像 Java 传统开发那样有成熟的课程和学习体系。我自己搭建相关技术时，也是通过各种博客摸索 🔍，不断测试尝试 ，才选出了适合业务场景的技术栈。

建议大家多思考自己需要什么知识，主动去查找资源 —— 无论是博客、论文还是 GitHub 上的代码，都要自己动手实践 👩💻，这样才能真正掌握，毕竟，纸上得来终觉浅，绝知此事要躬行 ✨！

*建议大家按选定的技术栈检索学习，以下学习资源由 AI 生成 🤖，可根据自身需求进一步检索补充哦～ *

### 5\.1 多 Agent 与工作流编排

- LangGraph 多 Agent 示例：适合参考“多个 Agent 如何分工协作、如何用图结构组织执行流程”。
[https://langchain\-ai\.github\.io/langgraph/tutorials/multi\_agent/multi\-agent\-collaboration/](https://langchain-ai.github.io/langgraph/tutorials/multi_agent/multi-agent-collaboration/)

- LangGraph / LangChain 官方参考文档：适合查 API、Agent、工具调用、状态管理等用法。
[https://reference\.langchain\.com/](https://reference.langchain.com/)

- AgentScope 官方文档：可参考其中的 Agent、Memory、RAG、Routing、Concurrent Agents 等模块。
[https://doc\.agentscope\.io/](https://doc.agentscope.io/)

### 5\.2 LangChain / LangGraph 基础

- LangChain Python 文档：适合学习模型调用、Prompt、工具、Agent、RAG 等基础能力。
[https://docs\.langchain\.com/oss/python/langchain/overview](https://docs.langchain.com/oss/python/langchain/overview)

- LangChain Retrieval 文档：适合学习如何构建知识库检索、文档加载、向量检索与 RAG。
[https://docs\.langchain\.com/oss/python/langchain/retrieval](https://docs.langchain.com/oss/python/langchain/retrieval)

- LangChain Memory 概念文档：适合理解短期记忆、长期记忆、跨会话记忆等设计。
[https://docs\.langchain\.com/oss/python/concepts/memory](https://docs.langchain.com/oss/python/concepts/memory)

- LangChain Long\-term Memory 文档：适合参考如何让 Agent 跨会话保存和召回用户信息。
[https://docs\.langchain\.com/oss/python/langchain/long\-term\-memory](https://docs.langchain.com/oss/python/langchain/long-term-memory)

### 5\.3 RAG基础概念

- RAG 基础课程与论文
https://blog\.csdn\.net/weixin\_32393347/article/details/146476986

### 5\.4 向量数据库

- 向量数据库的理解
https://blog\.csdn\.net/m0\_63171455/article/details/147295059

- Milvus 官方文档：
[https://milvus\.io/docs](https://milvus.io/docs)

- FAISS 官方文档：
[https://faiss\.ai/](https://faiss.ai/)

- Chroma 官方文档：
[https://docs\.trychroma\.com/](https://docs.trychroma.com/)

### 5\.5 Embedding 模型

- 主流模型对比
https://blog\.csdn\.net/Climbman/article/details/145972328

- SentenceTransformers 官方文档
https://www\.sbert\.net/

### 5\.6 Java / Spring AI 方向

- Spring AI 官方参考文档：适合使用 Java \+ Spring AI 的同学学习模型调用、向量库、工具调用、RAG 等能力。
[https://docs\.spring\.io/spring\-ai/reference/](https://docs.spring.io/spring-ai/reference/)

- Spring AI Tool Calling 文档：适合参考如何把 Java 方法封装成大模型可调用工具。
[https://docs\.spring\.io/spring\-ai/reference/api/tools\.html](https://docs.spring.io/spring-ai/reference/api/tools.html)

### 5\.7 大模型 API 接入

- 火山方舟 / 豆包大模型文档：适合接入豆包模型 API。
[https://www\.volcengine\.com/docs/82379](https://www.volcengine.com/docs/82379)

- DeepSeek API 文档：适合接入 DeepSeek 模型 API。
[https://api\-docs\.deepseek\.com/](https://api-docs.deepseek.com/)

- OpenAI API 文档：适合参考 OpenAI 兼容接口、Chat Completions、工具调用等设计。
[https://platform\.openai\.com/docs](https://platform.openai.com/docs)

---

## 六、小建议

建议按以下顺序推进：

1. 先完成单轮行程规划主链路  

2. 再补意图识别与多 Agent 调度  

3. 再补记忆能力  

4. 再补知识问答或信息查询  

5. 最后做并行调度、RAG、插件化、稳定性优化等加分项

不建议一开始就追求“大而全”哦。

---

## 七、评分重点说明

评分时重点关注以下几方面：

### 7\.1 基础完成度

- 是否完成了多 Agent 主链路

- 是否能正确处理核心任务

- 是否能跑通完整 demo

### 7\.2 设计合理性

- Agent 分工是否清晰

- 调度逻辑是否合理

- 模块边界是否明确

### 7\.3 智能性

- 是否使用 LLM 做语义理解

- 是否能结合上下文

- 是否能利用历史信息

- 是否能生成较自然、较完整的结果

### 7\.4 工程质量

- 代码结构是否清晰

- 可维护性是否较好

- 是否有异常处理、日志、测试

### 7\.5 加分项完成情况

- 两层记忆

- 并行调度

- 插件化架构

- 稳定性优化

- 测试评估

- 可视化界面

---

## 八、作业完成要求

*大家要对自己有信心💪：你遇到的困难，或许他人也正面对。无论未来是就业还是考研保研，都需要有马拉松式的坚持心态🏃♂️。即便只完成了 80%，也不妨提交作业尝试 —— 学长学姐会根据同批考生的整体水平酌情考量，千万不要放弃🙌。有问题欢迎咨询学长学姐，也可以暂时调整方向，选择其他考题🔄。*

### 8\.1 提交内容

大家只完成基础项就行哦！

需提交以下内容：

- 项目代码 整体打成压缩包\(包含 README 说明文档\)

- 核心功能演示截图或录屏

### 8\.2 README 至少应包含

- 项目简介

- 技术栈

- 系统架构

- Agent 列表与职责说明

- 运行方式说明

- 关键设计说明

- 核心示例

- 已完成基础项

- 已完成加分项

- 已知问题或后续优化方向

### 8\.3 演示建议

建议至少展示以下 3 类案例\(做的多的同学可以把做的都演示了\)：

- 行程规划案例

- 偏好记忆或历史记忆案例

- 知识问答或信息查询案例



### 8\.4 其他

- 截止日期 : 截止到 2026 年 8 月 25 日 \(没有完成的同学可以联系负责人延期哦\)

- 提交邮箱 : 邮箱地址：werun\_backend@163\.com

- 邮件主题格式：姓名\-后端\-QQ号\-第二阶段\-差旅晓问Agent平台（一定要按这格式写，不然可能找不到你的作业哦！）



