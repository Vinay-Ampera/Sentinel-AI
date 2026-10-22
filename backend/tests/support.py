"""Shared test helpers (imported as ``support``)."""

from typing import Any

from sentinel_ai.core.config import Settings

DUMMY_DB_URL = "postgresql://appuser:s3cretpw@dbhost.internal:5432/sentinel-ai"
PEPPER = "test-pepper-" + "x" * 32
ORIGIN = "http://localhost:5173"


def make_settings(database_url: str = DUMMY_DB_URL, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": database_url,
        "session_token_pepper": PEPPER,
        "session_cookie_secure": False,  # TestClient speaks plain http
        "login_max_failures": 3,
        "login_ip_max_attempts_per_minute": 1000,
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def make_zip(files: dict[str, bytes | str], *, compress: bool = True) -> bytes:
    """In-memory ZIP builder for tests."""
    import io
    import zipfile

    buf = io.BytesIO()
    kind = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(buf, "w", kind) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


SAMPLE_PROJECT: dict[str, bytes | str] = {
    "app/package.json": '{"dependencies": {"react": "18", "express": "4"}, '
    '"devDependencies": {"vite": "5", "jest": "29"}, '
    '"scripts": {"test": "jest", "build": "vite build"}}',
    "app/src/App.jsx": "export default () => null",
    "app/src/App.test.jsx": "test('x', () => {})",
    "api/requirements.txt": "fastapi==0.115\nopenai>=1\npytest\n# comment\n-r other.txt\n",
    "api/main.py": "print('hi')",
    "api/tests/test_main.py": "def test_x(): pass",
    "Dockerfile": "FROM python:3.12",
    ".github/workflows/ci.yml": "name: ci",
    ".env": "SECRET=do-not-store-me",
    "node_modules/left-pad/index.js": "module.exports = 1",
    "README.md": "# demo",
}
