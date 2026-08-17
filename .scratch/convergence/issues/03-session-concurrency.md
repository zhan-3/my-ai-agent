# 03 — 修复异步会话锁与锁生命周期

**Status:** ready-for-agent
**Blocked by:** None
**Type:** task
**Feature:** convergence

## 背景

`stream_chat()` 在事件循环中阻塞等待 `threading.Lock`。同会话第二个流可能阻塞整个循环，导致
持锁流无法继续。锁字典也不会回收。

## What to build

- 保持单实例内“读 recent → 运行图 → 写回”按会话串行的产品语义。
- 异步路径通过非阻塞事件循环的方式等待现有跨线程锁，例如 `await asyncio.to_thread(lock.acquire)`。
- 同步 `chat()`、异步 `stream_chat()` 和二者交错使用同一个会话协调模块。
- 为锁项增加引用计数或等价回收机制；完成且无等待者时删除长期不用的 session 项。
- 异常、取消和客户端断开都必须在 `finally` 中释放协调状态。

## 接口约束

- `Conversation.run/stream` 调用方不接触锁类型或生命周期。
- 本票只保证单进程语义；多实例顺序控制保留为独立后续设计。

## 验收

- [ ] 两个同 session 并发 stream 在超时内按顺序完成，不死锁。
- [ ] chat 与 stream 同 session 交错时写回仍成对有序。
- [ ] 不同 session 保持并行。
- [ ] 流取消和图异常后下一轮仍可取得锁。
- [ ] 大量一次性 session 完成后锁表不会等量永久增长。
- [ ] `scripts/gate.sh` 通过。

## 不做

- 不实现跨进程或跨容器分布式锁。
- 不改变 LangGraph 编排顺序。

