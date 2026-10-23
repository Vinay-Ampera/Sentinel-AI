# Sentinel AI sandbox runner image (Stages 8-9). Built locally from an already-present base:
#   make -C backend sandbox-image
# The pytest stack is vendored from backend/poetry.lock by sandbox/vendor.py (pure Python),
# so the build needs no network and nothing is downloaded. At run time the worker starts it
# with --network none, a read-only root filesystem, no capabilities and a non-root numeric
# user; see docs/architecture/SANDBOX_THREAT_MODEL.md.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="sentinel-sandbox-runner" \
      org.opencontainers.image.description="Disposable test sandbox for Sentinel AI (Stages 8-9)"

COPY entry.py smoke.py /opt/sentinel/
COPY vendor/ /opt/sentinel/site/
RUN chmod -R a=rX,u+w /opt/sentinel && chmod -R a-w /opt/sentinel

# 65534 (nobody) is only a numeric id here; the worker also passes --user 65534:65534.
USER 65534:65534
WORKDIR /workspace
ENV HOME=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANG=C.UTF-8
ENTRYPOINT ["python", "-I", "/opt/sentinel/entry.py"]
