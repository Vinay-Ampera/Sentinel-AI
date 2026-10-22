import pytest

from sentinel_ai.services.source_validation import (
    SourceRejected,
    validate_git_ref,
    validate_git_url,
    validate_localhost_url,
    validate_remote_url,
)


def code(fn, *args) -> str:  # type: ignore[no-untyped-def]
    with pytest.raises(SourceRejected) as err:
        fn(*args)
    return err.value.code


def test_valid_git_urls() -> None:
    assert (
        validate_git_url("https://github.com/org/repo.git").url == "https://github.com/org/repo.git"
    )
    assert validate_git_url("https://GitLab.com/a/b").host == "gitlab.com"
    assert validate_git_url("https://example.org:443/a/b").host == "example.org"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://github.com/o/r", "unsupported_scheme"),
        ("ssh://git@github.com/o/r", "unsupported_scheme"),
        ("git@github.com:o/r.git", "unsupported_scheme"),
        ("file:///etc/passwd", "unsupported_scheme"),
        ("git://github.com/o/r", "unsupported_scheme"),
        ("https://user:token@github.com/o/r", "credentials_in_url"),
        ("https://token@github.com/o/r", "credentials_in_url"),
        ("https://github.com:8443/o/r", "blocked_port"),
        ("https://github.com/o/r?x=1", "invalid_url"),
        ("https://github.com/o/r#frag", "invalid_url"),
        ("https://github.com", "invalid_url"),
        ("https://github.com/../etc", "invalid_url"),
        ("https://127.0.0.1/o/r", "blocked_host"),
        ("https://[::1]/o/r", "blocked_host"),
        ("https://10.0.0.5/o/r", "blocked_host"),
        ("https://192.168.1.10/o/r", "blocked_host"),
        ("https://169.254.169.254/latest", "blocked_host"),
        ("https://[::ffff:10.0.0.1]/o/r", "blocked_host"),
        ("https://2130706433/o/r", "blocked_host"),
        ("https://0x7f000001/o/r", "blocked_host"),
        ("https://localhost/o/r", "blocked_host"),
        ("https://metadata.google.internal/x/y", "blocked_host"),
        ("https://intranet/x/y", "blocked_host"),
        ("https://git.corp/x/y", "blocked_host"),
        ("https://github.com/o/r with space", "invalid_url"),
        ("https://github.com\\@evil.com/o/r", "invalid_url"),
        ("", "invalid_url"),
        (" https://github.com/o/r", "invalid_url"),
        ("https://github.com/" + "a" * 2100, "invalid_url"),
    ],
)  # fmt: skip
def test_invalid_git_urls(url: str, expected: str) -> None:
    assert code(validate_git_url, url) == expected


def test_git_refs() -> None:
    assert validate_git_ref(None) is None and validate_git_ref("") is None
    for ok in ("main", "release/1.2", "v1.0.0", "feature_x-1"):
        assert validate_git_ref(ok) == ok
    for bad in (
        "-upload-pack=x",
        "--help",
        "a..b",
        "a b",
        "x;rm",
        "a//b",
        "main.lock",
        "a/",
        "@{u}",
        "$(id)",
        "HEAD~1",
        "/abs",
        "a/.hidden",
        "x" * 300,
    ):
        assert code(validate_git_ref, bad) == "invalid_ref", bad


def test_localhost_urls() -> None:
    for ok in ("http://localhost:3000", "https://127.0.0.1:8443/app", "http://[::1]:5173/"):
        assert validate_localhost_url(ok).url == ok
    for bad in (
        "http://localhost.evil.com",
        "http://127.0.0.1.evil.com",
        "http://10.0.0.1",
        "http://0.0.0.0",
        "ftp://localhost",
        "http://user@localhost",
        "http://localhost:99999",
    ):
        assert code(validate_localhost_url, bad) in {
            "not_localhost",
            "unsupported_scheme",
            "credentials_in_url",
            "invalid_url",
        }, bad


def test_remote_urls() -> None:
    assert (
        validate_remote_url("https://staging.example.com/app", "staging").host
        == "staging.example.com"
    )
    assert (
        validate_remote_url("http://dev.example.com:8080", "development").host == "dev.example.com"
    )
    assert (
        code(validate_remote_url, "https://app.example.com", "production") == "production_blocked"
    )
    assert code(validate_remote_url, "https://app.example.com", "qa") == "invalid_environment"
    for bad in (
        "https://10.1.1.1",
        "http://169.254.169.254/",
        "https://localhost:3000",
        "https://svc.cluster.local",
        "https://u:p@example.com",
        "ftp://example.com",
        "https://example.com#x",
        "https://example.com:0",
    ):
        assert code(validate_remote_url, bad, "staging") in {
            "blocked_host",
            "credentials_in_url",
            "unsupported_scheme",
            "invalid_url",
            "blocked_port",
        }, bad


def test_validators_never_touch_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("network/DNS access attempted")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket.socket, "connect", boom)
    validate_git_url("https://github.com/o/r")
    validate_remote_url("https://staging.example.com", "staging")
    validate_localhost_url("http://localhost:3000")
