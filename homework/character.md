作业要求里有 6 个角色。拿出纸（或开个文件），对每个角色写出两句话：
① 三个条件里，哪个为它站台？为什么？
② 如果站不住，你会怎么处理——合并？降级成工具？




1. Intention Agent: 识别用户意图, 抽取关键信息, 决定后续子agent调用  
作为开头有必要, 意图识别需要纯用户输入 防止后续上下文污染

2. Orchestration Agent: 统一调度, 串并行执行, 结果汇总
有必要, 并行化执行子agent的基础
 
3. Event Collection Agent: 提取出发地、目的地、时间、人数、预算、出行目的等必要行程要素
这个可以

4. Preference Agent: 提取更新用户偏好 如酒店、交通、餐饮、出行风格
可以用程序代替

5. Memory Query Agent: 负责查询历史对话、历史行程、历史偏好
这个不是很清楚地位

6. RAG Agent: 负责企业差旅政策、报销规则、流程问答(根据document中的切片)
这个有必要

7. Information Query Agent: 联网或外部信息查询
这个专门的web-search模块感觉可以和rag以及memory统一成一个查询

8. Itinerary Planning Agent: 负责最终行程规划与结果生成
这个感觉可以用程序代替?