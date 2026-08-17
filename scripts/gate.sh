#!/usr/bin/env bash
# 提交前的确定性后端门禁。前端、真实模型与镜像验证由 CI 或按需命令负责。
#
# 首次运行：
#   scripts/init_test_db.sh
#   export POSTGRES_TEST_URL=postgresql://postgres:123456@localhost:5432/xiao_wen_test
#   scripts/gate.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ "$#" -ne 0 ]; then
  echo "scripts/gate.sh 不接受参数；真实模型和产品评测请使用 docs/test-map.md 中的按需命令。" >&2
  exit 2
fi
if [ -z "${POSTGRES_TEST_URL:-}" ]; then
  echo "错误：未设置 POSTGRES_TEST_URL；门禁拒绝回退到开发库。" >&2
  echo "请先运行 scripts/init_test_db.sh，并导出脚本打印的连接串。" >&2
  exit 2
fi

step() { echo; echo "== $1 =="; }

step "1/4 ruff check"
uv run ruff check src tests plugins scripts

step "2/4 ruff format --check"
uv run ruff format --check src tests plugins scripts

step "3/4 pytest（确定性后端测试）"
uv run pytest -q -m "not integration"

step "4/4 mypy"
uv run mypy src/xiao_wen tests scripts

echo
echo "✅ 后端门禁通过"
