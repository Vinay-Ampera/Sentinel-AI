"""Application settings.

Values come from process environment variables first, then from ``backend/.env``
(override the file with ``SENTINEL_ENV_FILE``). ``DATABASE_URL`` is the single source of
truth for the database connection: the app and Alembic both read it through
``DatabaseSettings``. Secrets are ``SecretStr`` and never appear in ``repr``, logs, or
error messages produced here.
"""

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = BACKEND_DIR / ".env"
_PLACEHOLDER_MARKERS = ("DB_PASSWORD", "DB_USER", "CHANGE_ME", "<password>")


class ConfigError(RuntimeError):
    """Invalid or missing configuration. The message never contains setting values."""


def env_file_path() -> Path:
    return Path(os.environ.get("SENTINEL_ENV_FILE") or DEFAULT_ENV_FILE)


class DatabaseSettings(BaseSettings):
    """Only the database connection; used by Alembic so migrations do not depend on
    unrelated (later-stage) settings."""

    model_config = SettingsConfigDict(
        env_file=env_file_path(),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: SecretStr
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_connect_timeout_seconds: int = 5

    @field_validator("database_url")
    @classmethod
    def _check_database_url(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value().strip()
        for prefix in ("postgresql://", "postgresql+psycopg://"):
            if raw.startswith(prefix):
                break
        else:
            raise ValueError("must start with postgresql:// or postgresql+psycopg://")
        if len(raw) <= len("postgresql://") or "@" not in raw and "host=" not in raw:
            raise ValueError("must include a host (postgresql://user:password@host:5432/dbname)")
        if any(marker in raw for marker in _PLACEHOLDER_MARKERS):
            raise ValueError("still contains an .env.example placeholder; set real values")
        if raw.startswith("postgresql://"):
            raw = "postgresql+psycopg://" + raw.removeprefix("postgresql://")
        return SecretStr(raw)

    @field_validator("db_pool_size", "db_max_overflow", "db_connect_timeout_seconds")
    @classmethod
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must be >= 0")
        return value

    @property
    def sqlalchemy_url(self) -> str:
        """URL for SQLAlchemy/Alembic (psycopg 3 driver). Contains the password."""
        return self.database_url.get_secret_value()


class Settings(DatabaseSettings):
    # --- Runtime (Stage 3) ---
    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    cors_allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    redis_timeout_seconds: float = 2.0

    # --- Sessions / auth (consumed from Stage 4; ADR-0002) ---
    session_token_pepper: SecretStr | None = None
    session_cookie_name: str = "sentinel_session"
    session_cookie_secure: bool = True
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    login_ip_max_attempts_per_minute: int = 20

    # --- Artifacts and uploads (consumed from Stage 6/8) ---
    artifact_storage_backend: Literal["local", "s3", "gcs"] = "local"
    artifact_storage_dir: Path = Path("./artifacts")
    upload_max_mb: int = 100
    zip_max_uncompressed_mb: int = 500
    zip_max_files: int = 20000

    # --- Job queue (Stage 7). Redis (REDIS_URL) is the broker only; PostgreSQL is truth. ---
    job_queue_name: str = "sentinel-jobs"
    job_executor: Literal["stub", "docker"] = "stub"  # "docker" is an explicit operator opt-in
    job_batch_size: int = 10
    job_max_concurrent_batches_per_run: int = 2
    job_max_concurrent_batches: int = 4
    job_lease_seconds: int = 60
    job_cancel_grace_seconds: int = 30
    job_max_attempts: int = 1
    job_retry_backoff_seconds: float = 5.0
    job_batch_timeout_seconds: int = 1800
    job_run_timeout_seconds: int = 3600
    job_queue_wait_seconds: int = 3600
    job_reconcile_interval_seconds: int = 30

    # --- Sandbox (Stage 8; only used when JOB_EXECUTOR=docker). Network is always "none". ---
    sandbox_image: str = "sentinel-sandbox-runner:stage8"
    sandbox_runtime: str | None = None  # e.g. "runsc" (gVisor) or a Kata runtime; default runc
    sandbox_scope: str = "default"  # label that scopes cleanup/janitor to this deployment/test
    sandbox_docker_bin: str | None = None
    sandbox_cpus: float = 1.0
    sandbox_memory_mb: int = 512
    sandbox_pids: int = 128
    sandbox_workspace_mb: int = 128
    sandbox_tmp_mb: int = 16
    sandbox_max_extract_mb: int = 96  # must fit the workspace tmpfs
    sandbox_max_file_mb: int = 32
    sandbox_test_timeout_seconds: int = 300
    sandbox_output_cap_bytes: int = 1_048_576
    sandbox_start_timeout_seconds: int = 60
    # Running a project's own code (pytest) is off unless the operator opts in, and then only
    # with a stronger runtime (SANDBOX_RUNTIME, e.g. gVisor/Kata) or an explicit acceptance of
    # the shared-kernel risk of plain Docker.
    sandbox_allow_project_code: bool = False
    sandbox_accept_shared_kernel: bool = False
    # --- Security scanners (Stage 10) ---
    # Semgrep is a compiled binary, so it lives in its own image built with network access by
    # the operator (sandbox/Dockerfile.semgrep). Rules are local files baked into that image.
    sandbox_scanner_image: str = "sentinel-scanner-runner:stage10"
    # The dependency audit is offline; refuse results from advisory data older than this
    # (the date is read from the image label set at build time, never from the container).
    dependency_advisory_max_age_days: int = 30
    # OWASP ZAP is the only sandbox that may have a network, and only toward one authorized
    # development/staging host. It stays disabled unless the operator names its image and an
    # egress-restricted Docker network AND attests that the host firewall limits that network
    # (docs/architecture/SANDBOX_THREAT_MODEL.md, "ZAP network").
    sandbox_zap_image: str | None = None
    sandbox_zap_network: str | None = None
    sandbox_zap_egress_attested: bool = False
    sandbox_zap_memory_mb: int = 2048
    sandbox_zap_tmp_mb: int = 256
    sandbox_zap_workspace_mb: int = 64
    sandbox_zap_pids: int = 512
    sandbox_zap_timeout_seconds: int = 1200

    # --- LLM (consumed from Stage 11) ---
    gemini_api_key: SecretStr | None = None
    gemini_model: str | None = None
    llm_max_tokens_per_run: int = 200_000
    llm_max_cost_usd_per_run: float = 2.0
    llm_max_cost_usd_per_day: float = 20.0

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def _no_wildcard_origin(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("wildcard origins are not allowed (credentials are used)")
        return value

    @field_validator(
        "redis_timeout_seconds",
        "session_idle_minutes",
        "session_absolute_hours",
        "login_max_failures",
        "login_lockout_minutes",
        "login_ip_max_attempts_per_minute",
        "upload_max_mb",
        "zip_max_uncompressed_mb",
        "zip_max_files",
        "job_batch_size",
        "job_max_concurrent_batches_per_run",
        "job_max_concurrent_batches",
        "job_lease_seconds",
        "job_cancel_grace_seconds",
        "job_max_attempts",
        "job_retry_backoff_seconds",
        "job_batch_timeout_seconds",
        "job_run_timeout_seconds",
        "job_queue_wait_seconds",
        "job_reconcile_interval_seconds",
        "sandbox_cpus",
        "sandbox_memory_mb",
        "sandbox_pids",
        "sandbox_workspace_mb",
        "sandbox_tmp_mb",
        "sandbox_max_extract_mb",
        "sandbox_max_file_mb",
        "sandbox_test_timeout_seconds",
        "sandbox_output_cap_bytes",
        "sandbox_start_timeout_seconds",
        "dependency_advisory_max_age_days",
        "sandbox_zap_memory_mb",
        "sandbox_zap_tmp_mb",
        "sandbox_zap_workspace_mb",
        "sandbox_zap_pids",
        "sandbox_zap_timeout_seconds",
        "llm_max_tokens_per_run",
        "llm_max_cost_usd_per_run",
        "llm_max_cost_usd_per_day",
    )
    @classmethod
    def _positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("must be > 0")
        return value

    @model_validator(mode="after")
    def _job_limits(self) -> "Settings":
        if self.job_max_attempts > 3:
            raise ValueError("JOB_MAX_ATTEMPTS must be <= 3")
        if self.job_batch_timeout_seconds > 86400 or self.job_run_timeout_seconds > 86400:
            raise ValueError("job timeouts must be <= 86400 seconds")
        if self.job_max_concurrent_batches_per_run > self.job_max_concurrent_batches:
            raise ValueError("per-run batch concurrency cannot exceed the global limit")
        return self

    @model_validator(mode="after")
    def _sandbox_limits(self) -> "Settings":
        if not re.fullmatch(r"[a-z0-9][a-z0-9_./:@-]{0,199}", self.sandbox_image):
            raise ValueError("SANDBOX_IMAGE must be a plain image reference")
        image_ref = r"[a-z0-9][a-z0-9_./:@-]{0,199}"
        for name, ref in (("SANDBOX_SCANNER_IMAGE", self.sandbox_scanner_image),
                          ("SANDBOX_ZAP_IMAGE", self.sandbox_zap_image)):  # fmt: skip
            if ref is not None and not re.fullmatch(image_ref, ref):
                raise ValueError(f"{name} must be a plain image reference")
        if self.sandbox_zap_network is not None and (
            not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", self.sandbox_zap_network)
            or self.sandbox_zap_network in ("host", "bridge", "none")
        ):
            raise ValueError("SANDBOX_ZAP_NETWORK must be a dedicated user-defined network name")
        if self.sandbox_zap_tmp_mb >= self.sandbox_zap_memory_mb:
            raise ValueError("SANDBOX_ZAP_TMP_MB must be smaller than SANDBOX_ZAP_MEMORY_MB")
        if self.sandbox_runtime is not None and not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", self.sandbox_runtime
        ):
            raise ValueError("SANDBOX_RUNTIME must be a plain runtime name")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", self.sandbox_scope):
            raise ValueError("SANDBOX_SCOPE must be a short plain label value")
        if self.sandbox_max_extract_mb >= self.sandbox_workspace_mb:
            raise ValueError("SANDBOX_MAX_EXTRACT_MB must be smaller than SANDBOX_WORKSPACE_MB")
        if self.sandbox_workspace_mb + self.sandbox_tmp_mb >= self.sandbox_memory_mb:
            raise ValueError("tmpfs sizes count against memory: raise SANDBOX_MEMORY_MB")
        if self.sandbox_max_file_mb > self.sandbox_max_extract_mb:
            raise ValueError("SANDBOX_MAX_FILE_MB cannot exceed SANDBOX_MAX_EXTRACT_MB")
        if self.sandbox_allow_project_code:
            if self.job_executor != "docker":
                raise ValueError("SANDBOX_ALLOW_PROJECT_CODE requires JOB_EXECUTOR=docker")
            if self.sandbox_runtime is None and not self.sandbox_accept_shared_kernel:
                raise ValueError(
                    "running project code needs SANDBOX_RUNTIME (gVisor/Kata) or an explicit "
                    "SANDBOX_ACCEPT_SHARED_KERNEL=true"
                )
        return self

    @model_validator(mode="after")
    def _production_requirements(self) -> "Settings":
        if self.app_env == "production":
            pepper = self.session_token_pepper
            if pepper is None or len(pepper.get_secret_value()) < 32:
                raise ValueError("SESSION_TOKEN_PEPPER (>= 32 chars) is required in production")
            if not self.session_cookie_secure:
                raise ValueError("SESSION_COOKIE_SECURE must be true in production")
        return self

    def artifact_root(self) -> Path:
        """Absolute artifact directory (relative paths resolve against backend/)."""
        path = self.artifact_storage_dir
        return (path if path.is_absolute() else BACKEND_DIR / path).resolve()

    @property
    def auth_configured(self) -> bool:
        pepper = self.session_token_pepper
        return pepper is not None and len(pepper.get_secret_value()) >= 32

    def pepper(self) -> str:
        """Session-token pepper; ConfigError (value-free) if missing or too short."""
        if not self.auth_configured or self.session_token_pepper is None:
            raise ConfigError("SESSION_TOKEN_PEPPER (>= 32 chars) is not configured")
        return self.session_token_pepper.get_secret_value()

    def safe_summary(self) -> dict[str, object]:
        """Non-secret view for startup logs and diagnostics."""
        return {
            "app_env": self.app_env,
            "log_level": self.log_level,
            "cors_allowed_origins": self.cors_allowed_origins,
            "artifact_storage_backend": self.artifact_storage_backend,
            "database_configured": True,
            "redis_configured": True,
            "auth_configured": self.auth_configured,
            "gemini_configured": self.gemini_api_key is not None,
        }


def format_validation_error(exc: ValidationError) -> str:
    """List offending variables and reasons without echoing any input value."""
    lines = []
    for err in exc.errors(include_input=False, include_url=False, include_context=False):
        name = ".".join(str(part) for part in err["loc"]).upper() or "SETTINGS"
        reason = (
            "is required" if err["type"] == "missing" else err["msg"].removeprefix("Value error, ")
        )
        lines.append(f"  - {name}: {reason}")
    return "\n".join(lines)


def load_settings[T: DatabaseSettings](cls: type[T], **kwargs: Any) -> T:
    """Load and validate settings, raising ConfigError with a value-free message."""
    try:
        return cls(**kwargs)
    except ValidationError as exc:
        raise ConfigError(
            f"Invalid configuration (checked environment and {env_file_path()}):\n"
            f"{format_validation_error(exc)}\n"
            "See backend/.env.example for the expected variables."
        ) from None


@lru_cache
def get_settings() -> Settings:
    return load_settings(Settings)
