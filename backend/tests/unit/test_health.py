from fastapi.testclient import TestClient

from sentinel_ai.core.config import Settings
from sentinel_ai.main import create_app


def _settings() -> Settings:
    return Settings(_env_file=None, database_url="postgresql://u:p@localhost:5432/x")  # type: ignore[call-arg]


def test_health_returns_ok() -> None:
    client = TestClient(create_app(_settings()))
    for path in ("/api/v1/health", "/api/v1/health/live"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
