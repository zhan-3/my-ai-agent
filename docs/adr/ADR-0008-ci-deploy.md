# ADR-0008：CI 分层 + Docker 部署

- 状态：已接受（2026-08）
- 相关：ADR-0007（JWT 认证）、ADR-0006（Postgres 后端）

## 背景

此前交付靠 `scripts/delivery.py gate`（本地命令集合，需 .env + 网络）——
无自动化 CI，无镜像化部署。产品化缺口的收口。

## 决策

1. **CI 平台 GitHub Actions**（`.github/workflows/ci.yml`）——仓库 remote 即 GitHub，
   零额外基础设施。
2. **分层 CI（核心取舍）**：
   - **单元层 job**：任何 push/PR 必跑——ruff + 格式 + mypy + 单元测试 +
     **PG 真库测试**（service container 起 postgres:16 + `POSTGRES_TEST_URL`）。
     无任何密钥，fork PR 也能完整运行。
   - **集成层 job**：真 LLM，**条件触发**（`secrets.DEEPSEEK_API_KEY != ''`）——
     主仓库有 secrets 才跑；fork PR 无 secrets 自动跳过。防密钥泄露优于 CI 完整性。
   - **镜像构建 job**：`docker build` 验证 Dockerfile 可构建。
3. **Docker 部署**：
   - `Dockerfile`：uv 官方组合镜像（python 3.11 + uv，glibc）、依赖层/源码层
     两段缓存、非 root（uid 1000）、`/healthz` 健康检查、`UV_LINK_MODE=copy`
     （WSL2 overlayfs 上 uv 硬链接解压 wheel 会 I/O 失败）。
   - `docker-compose.yml`：app + postgres 双服务，`depends_on: service_healthy`，
     API keys 经 `env_file: .env` 注入（gitignored，不入库）。

## 为什么不选别的

- **CI 全量含集成**：fork PR 拿不到 secrets → 必失败/必跳过，且密钥安全风险；
  分层后单元层是回归主力（93+ 无 LLM 测试），集成层作为主仓库增量验证。
- **裸进程部署（uv run + systemd）**：依赖主机 Python 环境、无隔离；Docker 镜像
  在 CI 可复现构建、部署端零环境假设。
- **uv:latest 基础镜像**：musl 版 uv 在 WSL2/overlayfs 上解压大 wheel 失败
  （0.12.x 实测）→ 改用官方组合镜像（glibc），且本机构建器（buildkit +
  containerd snapshotter）解压海量小文件有底层问题——完整镜像构建以 CI 为准，
  本机用运行时容器验证（bind mount 源码 + 依赖）。

## 后果

- 每次 push/PR：单元层全绿 + 镜像可构建；主仓库额外跑真 LLM 集成层。
- 部署 = `docker compose up -d --build`（先配 .env）；生产必须设强 `JWT_SECRET`。
- 本机 Docker 构建（WSL2）可能因构建器 bug 失败——以 GitHub CI 构建结果为准，
  本机运行时容器验证（等价逻辑已实测通过）。
