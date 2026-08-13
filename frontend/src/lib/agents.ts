// 子 Agent 注册表（与后端 INTENT 一一对应）：多 Agent 分工可视化
// 来源：旧单文件 index.html AGENTS 表，原样迁移

export interface AgentMeta {
  icon: string
  name: string
  desc: string
}

export const AGENTS: Record<string, AgentMeta> = {
  行程规划: { icon: '🗺️', name: '行程规划 Agent', desc: '要素提取 → 常驻城市记忆补全 → 生成逐日行程 → 写回长期记忆，并附目的地天气' },
  偏好记录: { icon: '💡', name: '偏好记忆 Agent', desc: '从一句话提取全部偏好（住宿/餐饮/交通/预算/常驻城市），写入长期记忆' },
  历史查询: { icon: '🕘', name: '历史查询 Agent', desc: '读取长期记忆中的历史行程，回顾上次出差' },
  知识问答: { icon: '📚', name: '知识库 Agent', desc: 'RAG 语义检索差旅政策文档，回答标准/制度类问题' },
  联网查询: { icon: '🌐', name: '联网查询 Agent', desc: 'ReAct 工具调用：天气（未来7天）/汇率/空气质量，带短期记忆指代消解' },
  其他: { icon: '🤝', name: '兜底 Agent', desc: '企业差旅范围外的问题，给出边界说明' },
  error: { icon: '⚠️', name: '系统异常', desc: '' },
}

export function agentOf(intent: string | undefined): AgentMeta {
  return AGENTS[intent ?? ''] ?? AGENTS['其他']
}

export const SUGGESTIONS = [
  '帮我规划10月8日去北京开会4天的行程',
  '出差住宿标准是什么',
  '北京明天天气怎么样',
  '我不吃辣，住宿喜欢安静',
  '我上次的行程是什么',
]
