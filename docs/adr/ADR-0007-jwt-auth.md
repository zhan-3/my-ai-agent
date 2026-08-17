# ADR-0007：JWT 认证 + 用户隔离

- 状态：已接受（2026-08）
- 相关：ADR-0006（Postgres 存储后端，会话隔离）、ADR-0002（会话循环，session_id 维度）

## 背景

ADR-0006 落地了按 `session_id` 的记忆隔离，但 README 诚实声明了边界：
**无用户认证——谁都能填任意 session_id**，隔离形同虚设。多用户应用需要
认证主体必须决定长期数据所有者；对话线程的后续拆分见 ADR-0009。

## 决策

1. **JWT 无状态认证**（pyjwt，HS256，payload 仅 sub/iat/exp，7 天有效期）：
   不选 Session Cookie（服务端会话存储，多进程需共享）、不选第三方 OAuth
   （钉钉/企业微信回调流程过重）——本地多 Agent 应用最小认证路径。
2. **密码哈希 bcrypt**（用户指定，非默认推荐的标准库 pbkdf2）：自动带盐，
   哈希落库非明文。
3. **用户存储 Postgres `users` 表**（username 唯一，与记忆后端共用 `POSTGRES_URL`；
   缺少配置时启动失败）。
   注册开放自建账号，注册即登录（直接返回 token），无种子管理员。
4. **用户隔离（核心）**：webapp 层强制从 `Authorization: Bearer <token>` 解出 `user_id`。
   客户端只提交 `conversation_id`；服务端派生用户作用域内的线程键，不能跨用户指定长期记忆所有者。
5. **不做授权**：单人个人数据，无 admin/普通用户之分（未来多角色再补）。
6. **前端最小登录/注册**：token 存 localStorage，聊天请求带 Authorization 头，
   401 自动退回登录页。

## 为什么不选别的

- **Session Cookie**：服务端会话状态，多进程/多副本需 Redis 共享——比 JWT 重，
  无需求支撑。
- **OAuth（钉钉/企业微信）**：企业差旅真实场景的终局，但引入外部应用登记 +
  回调流程；当前本地应用过重，列为未来接入项（JWT 签发可平滑保留为内部会话）。
- **jwt 密钥放代码**：不——`JWT_SECRET` 环境变量注入；代码内仅开发默认值
  （32+ 字节，README 注明生产必须覆盖）。

## 后果

- webapp 所有聊天请求需先注册/登录；未认证 401（前端自动退回登录页）。
- 记忆隔离语义由 ADR-0009 细分：线程 transcript 使用 `session_id`，长期记忆使用 `user_id`；
  内部 API 省略 `user_id` 时保持旧调用兼容。
- users 表只存 bcrypt 哈希；密码不落明文、日志不记密码。
- 用户和记忆均持久化到 Postgres；不提供进程内降级存储。
- 未来多角色授权、OAuth 接入、token 刷新均在 auth.py 内演进（单一接缝）。

## 后续变更（2026-08 单后端化）

- **InMemoryUserStore 删除**：用户存储唯一后端 Postgres users 表（`POSTGRES_URL`
  必配，未配报错，与 ADR-0006 同源）。webapp 测试不再注入内存用户存储，走真实 PG
  （conftest 每测试清 users 表）。
- 无角色授权、无 token 刷新的现状不变（仍在 auth.py 单接缝内演进）。
