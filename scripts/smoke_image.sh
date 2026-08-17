#!/usr/bin/env bash
set -euo pipefail

IMAGE="${1:-xiao-wen:ci}"
SUFFIX="$$-${RANDOM}"
NETWORK="xiao-wen-smoke-${SUFFIX}"
POSTGRES="xiao-wen-smoke-pg-${SUFFIX}"
APP="xiao-wen-smoke-app-${SUFFIX}"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/xiao-wen-smoke.XXXXXX")"

cleanup() {
  exit_code=$?
  trap - EXIT
  if [ "$exit_code" -ne 0 ] && docker inspect "$APP" >/dev/null 2>&1; then
    docker logs "$APP" >&2 || true
  fi
  docker rm -f "$APP" "$POSTGRES" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
  rm -rf "$TMP_DIR"
  exit "$exit_code"
}
trap cleanup EXIT

docker image inspect "$IMAGE" >/dev/null
docker network create "$NETWORK" >/dev/null
docker run -d --name "$POSTGRES" --network "$NETWORK" \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=123456 \
  -e POSTGRES_DB=xiao_wen \
  --health-cmd='pg_isready -U postgres -d xiao_wen' \
  --health-interval=1s --health-timeout=3s --health-retries=30 \
  postgres:16 >/dev/null

for _ in $(seq 1 30); do
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$POSTGRES")" = healthy ] && break
  sleep 1
done
[ "$(docker inspect --format '{{.State.Health.Status}}' "$POSTGRES")" = healthy ]

docker run -d --name "$APP" --network "$NETWORK" -p 127.0.0.1::8000 \
  -e POSTGRES_URL="postgresql://postgres:123456@${POSTGRES}:5432/xiao_wen" \
  -e JWT_SECRET=0123456789abcdef0123456789abcdef \
  -e DEEPSEEK_MODEL=smoke-model \
  -e DEEPSEEK_BASE_URL=http://127.0.0.1/unused \
  -e DEEPSEEK_API_KEY=smoke-key \
  -e DASHSCOPE_API_KEY=smoke-key \
  "$IMAGE" >/dev/null

PORT="$(docker inspect --format '{{(index (index .NetworkSettings.Ports "8000/tcp") 0).HostPort}}' "$APP")"
BASE_URL="http://127.0.0.1:${PORT}"
for _ in $(seq 1 30); do
  curl -fsS "$BASE_URL/livez" >"$TMP_DIR/livez.json" 2>/dev/null && break
  sleep 1
done
curl -fsS "$BASE_URL/readyz" >"$TMP_DIR/readyz.json"

curl -fsS "$BASE_URL/" >"$TMP_DIR/index.html"
! grep -q "晓问前端未构建" "$TMP_DIR/index.html"
grep -oE '(src|href)="/[^"]+"' "$TMP_DIR/index.html" \
  | sed -E 's/^[^=]+="([^"]+)"$/\1/' \
  | sort -u >"$TMP_DIR/assets.txt"
[ -s "$TMP_DIR/assets.txt" ]
while IFS= read -r asset; do
  curl -fsS "$BASE_URL$asset" >/dev/null
done <"$TMP_DIR/assets.txt"

python3 - "$TMP_DIR/readyz.json" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1], encoding="utf-8"))
assert report["ready"] is True
assert all(item["ready"] for item in report["checks"])
PY

docker exec "$APP" uv run --no-sync python -c '
from xiao_wen.rag import DOCS_DIR, load_chunks
documents = {path.stem for path in DOCS_DIR.glob("*.txt")}
sources = {source for source, _ in load_chunks()}
assert documents and sources == documents
'

printf 'smoke=passed image=%s assets=%s\n' "$IMAGE" "$(wc -l <"$TMP_DIR/assets.txt" | tr -d ' ')"
