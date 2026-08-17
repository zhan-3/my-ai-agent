"""Read-only process readiness checks for deployment orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path

import psycopg

from xiao_wen import ROOT
from xiao_wen.config import Settings, load_settings

RAG_DOCS_DIR = ROOT / "docs" / "documents"
FRONTEND_DIST = ROOT / "frontend" / "dist"
EXPECTED_RAG_DOCUMENTS = {
    "01_travel_standards.txt",
    "02_reimbursement_policy.txt",
    "03_booking_guide.txt",
    "04_faq.txt",
    "05_emergency_procedures.txt",
    "06_platform_guide.txt",
    "07_city_specific_tips.txt",
    "08_environmental_initiatives.txt",
}


@dataclass(frozen=True)
class ReadinessItem:
    name: str
    ready: bool
    detail: str


@dataclass(frozen=True)
class ReadinessReport:
    checks: tuple[ReadinessItem, ...]

    @property
    def ready(self) -> bool:
        return all(item.ready for item in self.checks)

    def as_dict(self) -> dict:
        return {
            "status": "ready" if self.ready else "unready",
            "ready": self.ready,
            "checks": [asdict(item) for item in self.checks],
        }


class _AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attribute = "src" if tag == "script" else "href" if tag == "link" else None
        if attribute is None:
            return
        for name, value in attrs:
            if name == attribute and value and value.startswith("/") and not value.startswith("//"):
                self.references.add(value.split("?", 1)[0].split("#", 1)[0])


def _probe_postgres(url: str) -> None:
    with psycopg.connect(url, connect_timeout=3) as connection:
        row = connection.execute("SELECT 1").fetchone()
    if row != (1,):
        raise RuntimeError("Postgres SELECT 1 未返回预期结果")


def _configuration_item(settings: Settings) -> ReadinessItem:
    checks = (
        settings.require_postgres_url,
        settings.require_jwt_secret,
        settings.require_llm,
        settings.require_embedding_key,
    )
    errors = []
    for check in checks:
        try:
            check()
        except RuntimeError as error:
            errors.append(str(error))
    return ReadinessItem("configuration", not errors, "配置完整" if not errors else "；".join(errors))


def _postgres_item(url: str, probe: Callable[[str], None]) -> ReadinessItem:
    try:
        probe(url)
    except Exception as error:
        return ReadinessItem("postgres", False, f"只读探测失败：{type(error).__name__}")
    return ReadinessItem("postgres", True, "SELECT 1 成功")


def _documents_item(directory: Path) -> ReadinessItem:
    available = {path.name for path in directory.glob("*.txt") if path.is_file() and path.stat().st_size > 0}
    missing = sorted(EXPECTED_RAG_DOCUMENTS - available)
    detail = f"{len(available)} 份语料可读" if not missing else "缺少：" + "、".join(missing)
    return ReadinessItem("rag_documents", not missing, detail)


def _frontend_item(directory: Path) -> ReadinessItem:
    index = directory / "index.html"
    if not index.is_file():
        return ReadinessItem("frontend_assets", False, "缺少 frontend/dist/index.html")
    parser = _AssetParser()
    parser.feed(index.read_text(encoding="utf-8"))
    base = directory.resolve()
    missing = []
    for reference in sorted(parser.references):
        candidate = (directory / reference.lstrip("/")).resolve()
        if not candidate.is_relative_to(base) or not candidate.is_file():
            missing.append(reference)
    if not parser.references:
        missing.append("HTML 未引用任何静态资源")
    detail = f"index + {len(parser.references)} 个静态引用可读" if not missing else "缺少：" + "、".join(missing)
    return ReadinessItem("frontend_assets", not missing, detail)


def check_readiness(
    *,
    settings: Settings | None = None,
    postgres_probe: Callable[[str], None] | None = None,
    docs_dir: Path | None = None,
    frontend_dist: Path | None = None,
) -> ReadinessReport:
    """Check required configuration and local/runtime dependencies without writes."""
    current = settings or load_settings()
    config_item = _configuration_item(current)
    postgres_url = current.postgres_url
    postgres_item = (
        _postgres_item(postgres_url, postgres_probe or _probe_postgres)
        if postgres_url
        else ReadinessItem("postgres", False, "缺少 POSTGRES_URL")
    )
    return ReadinessReport(
        (
            config_item,
            postgres_item,
            _documents_item(docs_dir or RAG_DOCS_DIR),
            _frontend_item(frontend_dist or FRONTEND_DIST),
        )
    )
