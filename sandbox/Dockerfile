# Sentinel AI sandbox runner image (Stages 8-10). Built locally from an already-present base:
#   make -C backend sandbox-image
# The pytest, Bandit and packaging stack is vendored from backend/poetry.lock by
# sandbox/vendor.py (pure Python), and the dependency audit's advisory bundle comes from
# sandbox/advisories/ (built by `make -C backend advisories`, the only step that needs the
# network), so this build needs no network and nothing is downloaded. At run time the worker
# starts it with --network none, a read-only root filesystem, no capabilities and a non-root
# numeric user; see docs/architecture/SANDBOX_THREAT_MODEL.md.
FROM python:3.12-slim

# Fetch time of the advisory data, set by the Makefile from advisories/meta.json. The host reads
# this label (not anything the container says) to refuse an audit on stale data.
ARG ADVISORY_FETCHED_AT=none
LABEL org.opencontainers.image.title="sentinel-sandbox-runner" \
      org.opencontainers.image.description="Disposable test and scan sandbox for Sentinel AI (Stages 8-10)" \
      sentinel.advisories.fetched_at="${ADVISORY_FETCHED_AT}"

COPY entry.py smoke.py dep_audit.py /opt/sentinel/
COPY vendor/ /opt/sentinel/site/
COPY advisories/ /opt/sentinel/advisories/
RUN chmod -R a=rX,u+w /opt/sentinel && chmod -R a-w /opt/sentinel

# 65534 (nobody) is only a numeric id here; the worker also passes --user 65534:65534.
USER 65534:65534
WORKDIR /workspace
ENV HOME=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANG=C.UTF-8
ENTRYPOINT ["python", "-I", "/opt/sentinel/entry.py"]
