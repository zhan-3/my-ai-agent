# 04 — 构建包含 UI 与知识语料的生产镜像

**Status:** ready-for-agent
**Blocked by:** 01
**Type:** task
**Feature:** convergence

## 背景

当前镜像只包含 Python 源码和插件。React 构建产物与 `docs/documents` 缺失，导致 Web 根页面和
RAG 政策能力在容器中不完整。

## What to build

- 使用 Node/pnpm 多阶段构建前端，锁文件安装并执行正式 build。
- 将 `frontend/dist` 和 `docs/documents` 复制到 Python 运行镜像中的预期路径。
- 创建可写的 `data/` 运行目录并保持非 root 用户；不复制本地 `data/chroma/`。
- 镜像不包含 `.env`、密钥、测试数据、评测产物或本地索引。
- 保持 `uv sync --frozen --no-dev` 和依赖层缓存。
- 更新 Docker 注释，删除 InMemory 兜底描述。

## 验收

- [ ] 干净构建上下文可以完成镜像构建。
- [ ] 容器 `/` 返回 React 页面而非“前端未构建”。
- [ ] HTML 引用的静态资源均返回 200。
- [ ] 容器内 `rag.load_chunks()` 能加载全部政策文档。
- [ ] 非 root 用户可创建 Chroma 锁和运行时索引目录。
- [ ] 镜像层和最终文件系统不包含 `.env` 或本地 Chroma。

## 不做

- 不预构建或提交 Chroma 索引。
- 不更换前端框架或 Python 基础运行方式。

