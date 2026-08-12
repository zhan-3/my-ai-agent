# 多 Agent 系统学习资源

## 知识（Knowledge）

- [Anthropic: Building multi-agent systems — When and how to use them](https://claude.com/blog/building-multi-agent-systems-when-and-how-to-use-them)
  多 Agent 领域最权威的第一手文章。何时该用多 Agent 的三个条件（上下文污染 / 并行化 / 专门化）、单 Agent 的局限信号、3–10 倍 token 代价。第一课核心依据。英文原文，建议配翻译工具精读。
- [Anthropic: Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)
  奠基文章：workflow 与 agent 的区分、"从最简单的方案开始"原则、orchestrator-workers 等模式的适用场景。
- [Anthropic: How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
  真实案例：并行化研究系统的实际架构、教训、token 消耗实测。做并行化时参考。
- [LangChain: Choosing the right multi-agent architecture](https://www.langchain.com/blog/choosing-the-right-multi-agent-architecture)
  架构选型：supervisor（主管）、handoffs、network（网络）等 LangGraph 模式的对比与选型依据。
- [LangGraph 官方文档: Workflows & Agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
  我们要用的框架的权威文档。写代码时随时查。
- [LangChain: LangGraph Multi-Agent Workflows](https://www.langchain.com/blog/langgraph-multi-agent-workflows)
  LangGraph 多 Agent 工作流的博客级介绍，比官方文档更易读的入门。

## 智慧（Wisdom / 社区）

- 暂无推荐。用户未表达加入社区的意愿，默认不推荐必须加入。如果以后想找人看真实项目、要反馈，再补充。

## 缺口（Gaps）

- 高质量的中文系统性多 Agent 教程较少，主要依赖英文原文 + 博客 + 翻译。第一课之后若发现需要中文材料，再补。
