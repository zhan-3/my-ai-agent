from pathlib import Path

import pytest

from xiao_wen import config


def test_dotenv_overrides_inherited_environment(monkeypatch, tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_MODEL=from-file\nJWT_SECRET=" + "f" * 32 + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    monkeypatch.setenv("DEEPSEEK_MODEL", "from-shell")

    settings = config.load_settings()

    assert settings.deepseek_model == "from-file"
    assert settings.jwt_secret == "f" * 32
    assert config.os.environ["DEEPSEEK_MODEL"] == "from-shell"


def test_test_database_url_wins_over_project_database(monkeypatch):
    monkeypatch.setenv("POSTGRES_URL", "postgresql://development")
    monkeypatch.setenv("POSTGRES_TEST_URL", "postgresql://test")
    assert config.load_settings().postgres_url == "postgresql://test"


@pytest.mark.parametrize(
    ("secret", "message"),
    [
        ("", "JWT_SECRET 未配置"),
        ("too-short", "长度不足"),
        (config._PUBLIC_JWT_SECRET, "公开开发默认值"),
    ],
)
def test_web_validation_rejects_unsafe_jwt(monkeypatch, secret: str, message: str):
    monkeypatch.setenv("POSTGRES_URL", "postgresql://configured")
    monkeypatch.setenv("JWT_SECRET", secret)
    with pytest.raises(RuntimeError, match=message):
        config.load_settings().validate_web()


def test_web_validation_requires_postgres(monkeypatch):
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.delenv("POSTGRES_TEST_URL", raising=False)
    monkeypatch.setenv("JWT_SECRET", "s" * 32)
    with pytest.raises(RuntimeError, match="POSTGRES_URL"):
        config.load_settings().validate_web()
