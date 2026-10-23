"""Chooses the executor from settings. ``stub`` is the default; ``docker`` is an explicit
operator opt-in that runs fixed catalog commands in disposable, network-less containers."""

from sentinel_ai.core.config import Settings
from sentinel_ai.execution.interface import Executor
from sentinel_ai.execution.stub import StubExecutor


def create_executor(settings: Settings) -> Executor:
    if settings.job_executor == "stub":
        return StubExecutor()
    if settings.job_executor == "docker":
        from sentinel_ai.execution.docker_executor import DockerSandboxExecutor

        return DockerSandboxExecutor(settings)
    raise ValueError("unsupported executor")
