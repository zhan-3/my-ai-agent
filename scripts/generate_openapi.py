"""Generate frontend TypeScript types from FastAPI without starting a server."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from xiao_wen.webapp import app

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "frontend" / "src" / "api" / "schema.generated.ts"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="xiao-wen-openapi-") as temp_dir:
        schema_path = Path(temp_dir) / "openapi.json"
        schema_path.write_text(json.dumps(app.openapi(), ensure_ascii=False), encoding="utf-8")
        subprocess.run(
            ["pnpm", "exec", "openapi-typescript", str(schema_path), "-o", str(output)],
            cwd=ROOT / "frontend",
            check=True,
        )


if __name__ == "__main__":
    main()
