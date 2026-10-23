# Sentinel AI sandbox runner image (Stage 8). Built locally from an already-present base:
#   make -C backend sandbox-image        (docker build -t sentinel-sandbox-runner:stage8 sandbox/)
# No packages are installed and nothing is downloaded at build time. At run time the worker
# starts it with --network none, a read-only root filesystem, no capabilities and a non-root
# numeric user; see docs/architecture/SANDBOX_THREAT_MODEL.md.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="sentinel-sandbox-runner" \
      org.opencontainers.image.description="Disposable test sandbox for Sentinel AI (Stage 8)"

COPY entry.py smoke.py /opt/sentinel/
RUN chmod 0444 /opt/sentinel/entry.py /opt/sentinel/smoke.py \
 && chmod 0555 /opt/sentinel

# 65534 (nobody) is only a numeric id here; the worker also passes --user 65534:65534.
USER 65534:65534
WORKDIR /workspace
ENV HOME=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANG=C.UTF-8
ENTRYPOINT ["python", "-I", "/opt/sentinel/entry.py"]
