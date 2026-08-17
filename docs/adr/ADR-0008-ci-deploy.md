# ADR-0008：CI 分层 + Docker 部署

- 状态：已接受（2026-08，精简更新）
- 相关：ADR-0007（JWT 认证）、ADR-0006（Postgres 后端）、ADR-0010（主管 Agent Loop）

## 背景

此前交付靠 `scripts/delivery.py gate`（本地命令集合，需 .env + 网络）——
无自动化 CI，无镜像化部署。产品化缺口的收口。

## 决策

1. **CI 平台 GitHub Actions**（`.github/workflows/ci.yml`）——仓库 remote 即 GitHub，
   零额外基础设施。
2. **分层 CI（核心取舍）**：
   - **后端 job**：master push 与 pull request 必跑确定性四步门禁；Postgres 16 service
     container 提供专用测试库。
   - **前端 job**：master push 与 pull request 独立运行 lint、test 和 build，不塞入本地后端门禁。
   - **OpenAPI 漂移**：HTTP 契约变化时按需运行，不为每次提交重复安装双栈依赖。
   - **镜像 job**：只在主分支或手动触发时构建并运行 smoke，不阻塞普通 PR。
   - **真实模型评测**：integration、意图契约和第三方实时诊断按需运行，不作为日常 CI 门禁。
3. **Docker 部署**：
   - `Dockerfile`：uv 官方组合镜像（python 3.11 + uv，glibc）、依赖层/源码层
     两段缓存、非 root（uid 1000）、`/livez` 健康检查、`UV_LINK_MODE=copy`（避免构建层之间
     的跨文件系统硬链接）。Python 3.11 与 `pyproject.toml` 和锁文件约束一致。
   - `docker-compose.yml`：app + PostgreSQL 16 双服务，`depends_on: service_healthy`，
     API keys 经 `env_file: .env` 注入（gitignored，不入库）。

## 为什么不选别的

- **CI 自动运行真实模型**：供应商波动、配额和密钥条件会制造与代码无关的红灯；这些检查保留为
  变更相关的按需评测，并单独报告结果。
- **本地门禁复刻完整前端和镜像 CI**：重复构建扩大反馈成本。提交前只保留确定性后端四步，
  前端、契约和镜像由对应改动面或 CI 验证。
- **裸进程部署（uv run + systemd）**：依赖主机 Python 环境、无隔离；Docker 镜像
  在 CI 可复现构建、部署端零环境假设。
- **仅依赖宿主机代理环境**：Docker 构建容器不会自动继承宿主机代理。需要访问外部包源时，
  显式传入 `HTTP_PROXY`、`HTTPS_PROXY` 和 `ALL_PROXY` 构建参数；纠正已缓存的直连失败步骤时，
  对对应阶段禁用缓存。代理参数本身不应写入镜像或仓库配置。
- **uv:latest 基础镜像**：继续使用 glibc 的 Python 3.11 + uv 官方组合镜像，以匹配项目
  Python 约束并减少 libc 差异；未再把先前下载失败归因于 uv 或 WSL2 解压缺陷。

## 后果

- master push 与 pull request：确定性后端门禁和前端检查；OpenAPI 在 HTTP 契约变化时按需检查；
  镜像 smoke 只在主分支或手动触发。
- 真实模型结果明确报告为按需证据，不与确定性 CI 混合，也不把未运行写成通过。
- 部署 = `docker compose up -d --build`（先配 .env）；生产必须设强 `JWT_SECRET`。
- 运维探针拆分为 `/livez` 与 `/readyz`：前者不访问外部依赖，后者只读检查必要配置、
  Postgres、RAG 文档和前端静态资源；`/healthz` 保留为 readiness 兼容入口。
- 本机构建已用显式代理参数验证；`scripts/smoke_image.sh` 启动隔离依赖并复用 CI 的镜像验收。
- Compose、CI 与 smoke 固定 PostgreSQL 16；旧浮动版本卷必须通过逻辑备份迁移，
  不能把更高 major 的数据目录直接挂给 16。
