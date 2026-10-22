from pathlib import Path

import pytest

from sentinel_ai.core.config import ConfigError, DatabaseSettings, Settings, load_settings

URL = "postgresql://appuser:s3cretpw@localhost:5432/sentinel-ai"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate from the developer's shell and real backend/.env."""
    import os

    for key in list(os.environ):
        if key.upper() in {f.upper() for f in Settings.model_fields}:
            monkeypatch.delenv(key, raising=False)


def make(**kwargs: object) -> Settings:
    return load_settings(Settings, _env_file=None, **kwargs)


def test_missing_database_url_gives_clear_error() -> None:
    with pytest.raises(ConfigError) as err:
        make()
    assert "DATABASE_URL: is required" in str(err.value)
    assert ".env.example" in str(err.value)


def test_database_url_normalized_to_psycopg_driver() -> None:
    assert make(database_url=URL).sqlalchemy_url.startswith("postgresql+psycopg://")


def test_hyphenated_database_name_accepted() -> None:
    assert make(database_url=URL).sqlalchemy_url.endswith("/sentinel-ai")


@pytest.mark.parametrize(
    "bad",
    [
        "mysql://u:p@h/db",
        "postgresql://",
        "postgresql://DB_USER:DB_PASSWORD@localhost:5432/sentinel-ai",
    ],
)
def test_invalid_database_urls_rejected_without_echoing_value(bad: str) -> None:
    with pytest.raises(ConfigError) as err:
        make(database_url=bad)
    assert "DATABASE_URL" in str(err.value)
    if len(bad) > len("postgresql://"):  # the hint itself mentions the bare scheme
        assert bad not in str(err.value)


def test_error_message_never_contains_secret_values() -> None:
    with pytest.raises(ConfigError) as err:
        make(database_url=URL, log_level="LOUD", session_token_pepper="topsecretpepper")
    text = str(err.value)
    assert "LOG_LEVEL" in text
    assert "s3cretpw" not in text and "topsecretpepper" not in text


def test_secrets_hidden_from_repr_and_summary() -> None:
    s = make(database_url=URL, gemini_api_key="gem-key-123")
    assert "s3cretpw" not in repr(s) and "gem-key-123" not in repr(s)
    assert "s3cretpw" not in str(s.safe_summary())
    assert s.safe_summary()["gemini_configured"] is True


def test_defaults() -> None:
    s = make(database_url=URL)
    assert s.app_env == "development"
    assert s.cors_allowed_origins == ["http://localhost:5173"]
    assert s.redis_url.get_secret_value() == "redis://localhost:6379/0"
    assert s.session_idle_minutes == 30 and s.session_cookie_secure is True


def test_cors_origins_comma_separated_and_wildcard_rejected() -> None:
    s = make(database_url=URL, cors_allowed_origins="http://a.test, http://b.test")
    assert s.cors_allowed_origins == ["http://a.test", "http://b.test"]
    with pytest.raises(ConfigError):
        make(database_url=URL, cors_allowed_origins="*")


def test_non_positive_numbers_rejected() -> None:
    with pytest.raises(ConfigError) as err:
        make(database_url=URL, session_idle_minutes=0)
    assert "SESSION_IDLE_MINUTES" in str(err.value)


def test_production_requires_pepper_and_secure_cookie() -> None:
    with pytest.raises(ConfigError) as err:
        make(database_url=URL, app_env="production")
    assert "SESSION_TOKEN_PEPPER" in str(err.value)
    ok = make(database_url=URL, app_env="production", session_token_pepper="x" * 32)
    assert ok.app_env == "production"
    with pytest.raises(ConfigError):
        make(
            database_url=URL,
            app_env="production",
            session_token_pepper="x" * 32,
            session_cookie_secure=False,
        )


def test_env_vars_override_env_file_and_file_is_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text(f"DATABASE_URL={URL}\nLOG_LEVEL=DEBUG\nUNRELATED=ignored\n")
    s = load_settings(Settings, _env_file=env_file)
    assert s.log_level == "DEBUG"
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    assert load_settings(Settings, _env_file=env_file).log_level == "ERROR"


def test_database_settings_alone_ignore_other_invalid_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "LOUD")  # invalid for Settings, irrelevant to Alembic
    env_file = tmp_path / "db.env"
    env_file.write_text(f"DATABASE_URL={URL}\n")
    assert load_settings(DatabaseSettings, _env_file=env_file).sqlalchemy_url.endswith(
        "sentinel-ai"
    )
