#!/usr/bin/env bash
# 在 Compose Postgres 中幂等创建专用测试库；不会修改开发库中的表或数据。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

docker compose up -d postgres
until docker compose exec -T postgres pg_isready -U postgres -d postgres >/dev/null 2>&1; do
  sleep 1
done

docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d postgres <<'SQL'
SELECT 'CREATE DATABASE xiao_wen_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'xiao_wen_test')\gexec
SQL

echo "测试库已就绪。运行："
echo "export POSTGRES_TEST_URL=postgresql://postgres:123456@localhost:5432/xiao_wen_test"
