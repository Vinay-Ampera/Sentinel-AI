# Sentinel AI ZAP image: the official OWASP ZAP stable image behind the Sentinel runner.
#   make -C backend zap-image ZAP_BASE=<image reference you have reviewed and pinned>
#
# UNVERIFIED: this file was written without being able to pull or run ZAP (no network in the
# development environment). The paths below (/zap/zap-baseline.py, /zap/wrk, python3, java on
# PATH) follow the public ZAP docker documentation; build it, then run the checklist in
# docs/architecture/SANDBOX_THREAT_MODEL.md ("ZAP verification") before enabling ZAP.
#
# The worker starts this image with a read-only root filesystem, no capabilities, a non-root
# numeric user, tmpfs scratch space, a black-hole DNS server and ONLY the operator-provisioned,
# firewall-restricted network named in SANDBOX_ZAP_NETWORK (never the default bridge or host).
ARG ZAP_BASE
FROM ${ZAP_BASE}

USER root
COPY entry.py /opt/sentinel/entry.py
# ZAP's scripts write reports under /zap/wrk and copy /tmp/zap.yaml there, so /zap/wrk must
# be a DIFFERENT tmpfs from /tmp (a link to /tmp makes that copy fail): use /workspace, from
# which the in-image runner frames /workspace/zap.json back to the host.
RUN rm -rf /zap/wrk && ln -s /workspace /zap/wrk && chmod -R a=rX /opt/sentinel
ENV SENTINEL_PYTHONPATH="" SENTINEL_PATH="/usr/local/bin:/usr/bin:/bin" \
    SENTINEL_JAVA_TOOL_OPTIONS="-Duser.home=/tmp -Xmx1g"
LABEL sentinel.scanner="zap"
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT ["python3", "-I", "/opt/sentinel/entry.py"]
