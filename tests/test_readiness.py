"""Readiness is read-only and reports each required deployment dependency."""

from pathlib import Path

from xiao_wen.config import Settings
from xiao_wen.readiness import EXPECTED_RAG_DOCUMENTS, check_readiness


def _settings() -> Settings:
    return Settings(
        deepseek_model="test-model",
        deepseek_base_url="https://example.test/v1",
        deepseek_api_key="test-key",
        dashscope_api_key="embed-key",
        dashscope_emb_model="text-embedding-v3",
        dashscope_emb_dim="1024",
        rag_min_sim="0.35",
        postgres_url="postgresql://test",
        jwt_secret="x" * 32,
    )


def _runtime_assets(tmp_path: Path) -> tuple[Path, Path]:
    docs = tmp_path / "documents"
    docs.mkdir()
    for name in EXPECTED_RAG_DOCUMENTS:
        (docs / name).write_text("政策内容", encoding="utf-8")
    frontend = tmp_path / "dist"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    (frontend / "index.html").write_text('<script src="/assets/app.js"></script>', encoding="utf-8")
    return docs, frontend


def test_readiness_passes_with_read_only_dependencies(tmp_path):
    docs, frontend = _runtime_assets(tmp_path)
    probes = []

    def record_probe(url: str) -> None:
        probes.append(url)

    report = check_readiness(
        settings=_settings(),
        postgres_probe=record_probe,
        docs_dir=docs,
        frontend_dist=frontend,
    )

    assert report.ready is True
    assert probes == ["postgresql://test"]
    assert all(item.ready for item in report.checks)


def test_readiness_fails_for_postgres_documents_or_frontend(tmp_path):
    docs, frontend = _runtime_assets(tmp_path)

    postgres_report = check_readiness(
        settings=_settings(),
        postgres_probe=lambda url: (_ for _ in ()).throw(ConnectionError("down")),
        docs_dir=docs,
        frontend_dist=frontend,
    )
    assert next(item for item in postgres_report.checks if item.name == "postgres").ready is False

    missing_docs = tmp_path / "missing-docs"
    missing_docs.mkdir()
    docs_report = check_readiness(
        settings=_settings(),
        postgres_probe=lambda url: None,
        docs_dir=missing_docs,
        frontend_dist=frontend,
    )
    assert next(item for item in docs_report.checks if item.name == "rag_documents").ready is False

    missing_frontend = tmp_path / "missing-frontend"
    missing_frontend.mkdir()
    frontend_report = check_readiness(
        settings=_settings(),
        postgres_probe=lambda url: None,
        docs_dir=docs,
        frontend_dist=missing_frontend,
    )
    assert next(item for item in frontend_report.checks if item.name == "frontend_assets").ready is False


def test_default_postgres_probe_only_executes_select(monkeypatch):
    from xiao_wen import readiness

    statements = []

    class Result:
        def fetchone(self):
            return (1,)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, statement):
            statements.append(statement)
            return Result()

    monkeypatch.setattr(readiness.psycopg, "connect", lambda url, connect_timeout: Connection())
    readiness._probe_postgres("postgresql://test")

    assert statements == ["SELECT 1"]
