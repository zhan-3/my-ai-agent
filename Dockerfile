# 晓问 · 差旅出行助手 生产镜像
# 构建：docker build -t xiao-wen .
# 运行：docker compose up -d（推荐，含 Postgres）或：
#       docker run -d -p 8000:8000 --env-file .env xiao-wen
#
# 基础镜像用 uv 官方组合镜像（python 3.11 + uv，glibc）——uv:latest(musl)
# 在 WSL2/overlayfs 上解压大 wheel 会 I/O 失败（0.12.x 已知问题）
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# 包索引源可配置（默认官方 PyPI；受限网络构建时 --build-arg 覆盖国内镜像）
ARG UV_DEFAULT_INDEX=https://pypi.org/simple
ENV UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX}
# 硬链接模式在 WSL2/overlayfs 上解压 wheel 会 I/O 失败 → 强制 copy 模式
ENV UV_LINK_MODE=copy
# 慢源（国内镜像）下 psycopg-binary 等大 wheel 下载超 30s → 调大 HTTP 超时
ENV UV_HTTP_TIMEOUT=300

# ① 依赖层（仅 pyproject + lock，命中缓存则跳过，加速重建）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ② 源码层（README 是 pyproject 声明文件，项目安装必需）
COPY README.md ./
COPY src ./src
COPY plugins ./plugins
RUN uv sync --frozen --no-dev

# 非 root 运行（容器安全基线）
RUN useradd --create-home --uid 1000 xw && chown -R xw:xw /app
USER xw

# 记忆后端：留空 = InMemory 演示兜底；生产 compose 注入 Postgres URL
ENV POSTGRES_URL=""

EXPOSE 8000

# 健康检查走 /healthz（纯本地探活，不依赖 LLM）
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD ["uv", "run", "--no-sync", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

CMD ["uv", "run", "--no-sync", "python", "-m", "xiao_wen.webapp"]
