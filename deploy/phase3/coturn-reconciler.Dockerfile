ARG PYTHON_BASE_IMAGE
FROM ${PYTHON_BASE_IMAGE}
ARG PYTHON_BASE_IMAGE
RUN /usr/local/bin/python3 -c 'import os,re,sys; image=os.environ.get("PYTHON_BASE_IMAGE",""); sys.exit(0 if re.search(r"@sha256:[0-9a-f]{64}$", image) else 1)' || \
    { echo "PYTHON_BASE_IMAGE must be pinned as name@sha256:<64 hex chars>" >&2; exit 1; }

COPY scripts/phase3/coturn_reconcile.py /opt/vibe/scripts/coturn_reconcile.py
COPY scripts/phase3/coturn_cli_control.py /opt/vibe/scripts/coturn_cli_control.py
RUN chmod 0555 /opt/vibe/scripts/coturn_reconcile.py /opt/vibe/scripts/coturn_cli_control.py

USER 65532:65532
ENTRYPOINT ["/usr/local/bin/python3"]
