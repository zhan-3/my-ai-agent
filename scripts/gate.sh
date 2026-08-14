#!/usr/bin/env bash
# 本地质量门禁：复刻 CI unit job 的四步（ruff check → ruff format --check → pytest → mypy）。
# 用法：
#   scripts/gate.sh                # 门禁四步（对应 CI unit job，需 Postgres 测试库）
#   scripts/gate.sh --integration  # 门禁 + 集成测试（真 LLM，需 .env 密钥）
#   scripts/gate.sh --golden       # 门禁 + 黄金集回归（真 LLM）
#   scripts/gate.sh --full         # 门禁 + integration + golden（对应 CI integration job）
#
# 注意：pytest 的 conftest 优先用 POSTGRES_TEST_URL；未设置时会落到 POSTGRES_URL，
# 可能清掉开发库数据——本地请务必 export POSTGRES_TEST_URL=postgresql://postgres:123456@localhost:5432/xiao_wen_test
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE=unit
for arg in "$@"; do
  case "$arg" in
    --integration) MODE=integration ;;
    --golden) MODE=golden ;;
    --full) MODE=full ;;
    *)
      echo "未知参数：$arg（支持 --integration / --golden / --full）" >&2
      exit 2
      ;;
  esac
done

if [ -z "${POSTGRES_TEST_URL:-}" ]; then
  echo "⚠️  未设置 POSTGRES_TEST_URL：conftest 将回退到 POSTGRES_URL（若指向开发库会被清空！）"
  echo "    建议先 export POSTGRES_TEST_URL=postgresql://postgres:123456@localhost:5432/xiao_wen_test"
fi

step() { echo; echo "== $1 =="; }

step "1/4 ruff check"
uv run ruff check src tests plugins scripts

step "2/4 ruff format --check"
uv run ruff format --check src tests scripts

step "3/4 pytest（单元层，不跑 integration）"
uv run pytest -q -m "not integration"

step "4/4 mypy"
uv run mypy src/xiao_wen tests scripts

if [ "$MODE" = integration ] || [ "$MODE" = full ]; then
  step "5/6 pytest（集成层，真 LLM）"
  uv run pytest -q -m integration
fi
if [ "$MODE" = golden ] || [ "$MODE" = full ]; then
  step "6/6 黄金集回归（意图分类）"
  uv run python scripts/golden_intents.py --threshold 0.95
fi

echo
echo "✅ 门禁通过（$MODE）"
