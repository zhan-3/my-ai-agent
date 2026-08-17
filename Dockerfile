# 晓问 · 差旅出行助手 生产镜像
# 构建：docker build -t xiao-wen .
# 运行：docker compose up -d（推荐，含 Postgres）或：
#       docker run -d -p 8000:8000 --env-file .env xiao-wen
# 代理：构建容器不会自动继承宿主代理；需要时显式传入
#       --build-arg HTTP_PROXY --build-arg HTTPS_PROXY --build-arg NO_PROXY
#
# Python 运行时使用 glibc 版 3.11，与 pyproject.toml 和 uv.lock 的版本约束一致。
FROM node:22-bookworm-slim AS frontend-builder

ARG PNPM_VERSION=11.21.0
RUN npm install --global pnpm@${PNPM_VERSION}

WORKDIR /frontend

COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend ./
RUN pnpm build


FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS runtime

WORKDIR /app

# 包索引源可配置（默认官方 PyPI；受限网络构建时 --build-arg 覆盖国内镜像）
ARG UV_DEFAULT_INDEX=https://pypi.org/simple
ENV UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX}
# 容器层中使用复制模式，避免 uv 缓存与虚拟环境跨文件系统硬链接。
ENV UV_LINK_MODE=copy
# 容忍受限网络下的大 wheel 下载波动。
ENV UV_HTTP_TIMEOUT=300

# ① 依赖层（仅 pyproject + lock，命中缓存则跳过，加速重建）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ② 源码层（README 是 pyproject 声明文件，项目安装必需）
COPY README.md ./
COPY src ./src
COPY plugins ./plugins
RUN uv sync --frozen --no-dev

# ③ 运行资产：React 产物 + RAG 原始语料；Chroma 由非 root 用户首次查询时在 data/ 构建
COPY --from=frontend-builder /frontend/dist ./frontend/dist
COPY docs/documents ./docs/documents

# 非 root 运行（容器安全基线）；data/ 仅保存运行时状态，不从构建上下文复制本地索引
RUN mkdir -p data && useradd --create-home --uid 1000 xw && chown -R xw:xw /app
USER xw

EXPOSE 8000

# Docker 只判断进程存活；依赖就绪由 /readyz 单独判断。
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD ["uv", "run", "--no-sync", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/livez', timeout=2)"]

CMD ["uv", "run", "--no-sync", "python", "-m", "xiao_wen.webapp"]
