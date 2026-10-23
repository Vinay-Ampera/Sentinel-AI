"""Trusted runner inside the sandbox container (standard library only).

    entry.py [--extract MAX_ZIP_BYTES MAX_FILES MAX_TOTAL_BYTES MAX_FILE_BYTES]
             [--result-file PATH NONCE MAX_BYTES] --timeout SECONDS -- COMMAND [ARG ...]

With --extract the source archive is read from stdin (bounded) and extracted into
/workspace/src with strict checks; then COMMAND runs with a minimal environment and a hard
timeout. The command is chosen by the Sentinel worker from a fixed table, never from user
input. Everything this process reads (the archive) and everything COMMAND prints is
untrusted data for the host, which derives the result from the container's exit state.

With --result-file, after COMMAND ends (even on timeout) this trusted process reads PATH (a
regular file, never a symlink, size-capped) and prints it as one framed, base64 block on
stdout. The host parses the last frame carrying its NONCE and treats the content as
untrusted data: the file is written by the project's own code, so it can only describe the
project's own tests.

Exit codes: 70 archive rejected, 71 usage error, 124 timeout; otherwise the command's own.
"""

import base64
import hashlib
import os
import posixpath
import signal
import stat
import subprocess
import sys
import tempfile
import zipfile

EXIT_REJECTED = 70
EXIT_USAGE = 71
EXIT_TIMEOUT = 124
WORKSPACE = "/workspace"
SOURCE = "/workspace/src"
MAX_DEPTH = 32
MAX_NAME = 255


class Rejected(Exception):
    pass


def reject(msg: str) -> "None":
    raise Rejected(msg)


def read_stdin_bounded(limit: int, dest: str) -> None:
    total = 0
    with open(dest, "wb") as out:
        while True:
            chunk = sys.stdin.buffer.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                reject("archive is larger than the sandbox limit")
            out.write(chunk)
    if total == 0:
        reject("no archive was provided")


def check_name(name: str) -> list[str]:
    if not name or len(name) > 512 or "\x00" in name or "\\" in name:
        reject("unsafe entry name")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        reject("absolute entry path")
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        reject("control character in entry name")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or ".." in parts or len(parts) > MAX_DEPTH or any(len(p) > MAX_NAME for p in parts):
        reject("unsafe entry path")
    return parts


def extract(zip_path: str, max_files: int, max_total: int, max_file: int) -> None:
    os.makedirs(SOURCE, mode=0o700, exist_ok=True)
    root = os.path.realpath(SOURCE)
    files = 0
    total = 0
    seen: set[str] = set()
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError):
        reject("not a valid ZIP archive")
    with zf:
        infos = zf.infolist()
        if len(infos) > max_files:
            reject("too many entries")
        for info in infos:
            parts = check_name(info.filename)
            rel = posixpath.join(*parts)
            if rel in seen:
                reject("duplicate entry")
            seen.add(rel)
            if info.flag_bits & 0x1:
                reject("encrypted entry")
            kind = stat.S_IFMT((info.external_attr >> 16) & 0xFFFF)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR):  # 0: no type recorded (plain file)
                reject("special file or symlink in archive")
            target = os.path.realpath(os.path.join(root, *parts))
            if os.path.commonpath([root, target]) != root or target == root:
                reject("entry escapes the workspace")
            if info.is_dir():
                os.makedirs(target, mode=0o700, exist_ok=True)
                continue
            files += 1
            if files > max_files:
                reject("too many files")
            os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
            written = 0
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as out, zf.open(info) as src:
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    written += len(chunk)
                    total += len(chunk)
                    if written > max_file or total > max_total:
                        reject("archive expands beyond the sandbox limit")
                    out.write(chunk)


def emit_result(path: str, nonce: str, limit: int) -> None:
    """Print PATH as a framed base64 block (see module docstring). Silent if unusable."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            return
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining > 0:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    except OSError:
        return
    finally:
        os.close(fd)
    if len(data) > limit:
        return
    out = sys.stdout.buffer
    out.write(f"\n@@SENTINEL-RESULT {nonce} {len(data)} {hashlib.sha256(data).hexdigest()}\n".encode())
    encoded = base64.b64encode(data)
    for i in range(0, len(encoded), 76):
        out.write(encoded[i : i + 76] + b"\n")
    out.write(f"@@SENTINEL-END {nonce}\n".encode())
    out.flush()


def run_command(argv: list[str], timeout: float, cwd: str) -> int:
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "PYTHONPATH": "/opt/sentinel/site",  # vendored pytest, read-only
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    proc = subprocess.Popen(  # noqa: S603 - argv comes from the worker's fixed table
        argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, start_new_session=True
    )
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        print("sandbox: command exceeded its time limit", file=sys.stderr)
        return EXIT_TIMEOUT


def main(args: list[str]) -> int:
    extract_limits: list[int] | None = None
    result_file: tuple[str, str, int] | None = None
    timeout = 60.0
    try:
        i = 0
        while i < len(args) and args[i] != "--":
            if args[i] == "--extract":
                extract_limits = [int(v) for v in args[i + 1 : i + 5]]
                if len(extract_limits) != 4 or min(extract_limits) <= 0:
                    return EXIT_USAGE
                i += 5
            elif args[i] == "--result-file":
                result_file = (args[i + 1], args[i + 2], int(args[i + 3]))
                if not args[i + 2].isalnum() or result_file[2] <= 0:
                    return EXIT_USAGE
                i += 4
            elif args[i] == "--timeout":
                timeout = float(args[i + 1])
                i += 2
            else:
                return EXIT_USAGE
        command = args[i + 1 :]
    except (ValueError, IndexError):
        return EXIT_USAGE
    if not command or timeout <= 0:
        return EXIT_USAGE

    cwd = WORKSPACE
    if extract_limits is not None:
        max_zip, max_files, max_total, max_file = extract_limits
        try:
            with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
                path = os.path.join(tmp, "source.zip")
                read_stdin_bounded(max_zip, path)
                extract(path, max_files, max_total, max_file)
        except Rejected as exc:
            print(f"sandbox: archive rejected: {exc}", file=sys.stderr)
            return EXIT_REJECTED
        except OSError as exc:
            print(f"sandbox: archive could not be extracted: {exc.strerror}", file=sys.stderr)
            return EXIT_REJECTED
        cwd = SOURCE
    code = run_command(command, timeout, cwd)
    if result_file is not None:
        emit_result(*result_file)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
