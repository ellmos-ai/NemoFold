FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    NEMOFOLD_MAX_PARALLEL_JOBS=2

WORKDIR /app

# Keep the public image intentionally smaller than the repository. It receives the
# application and the synthetic corpus, but no private inputs, run reports or videos.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY examples/synthetic-home ./examples/synthetic-home

RUN python -m pip install --no-cache-dir . \
    && addgroup --system --gid 10001 nemofold \
    && adduser --system --uid 10001 --ingroup nemofold \
        --home /nonexistent --no-create-home nemofold

USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=4s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/api/status',timeout=3).close()"]

# serve-demo fixes the roots and policy server-side. It has no file-action or external-
# model switches, so a public visitor cannot widen authority through request data.
CMD ["sh", "-c", "exec python -m nemofold serve-demo --demo-root /app/examples/synthetic-home --host 0.0.0.0 --port \"${PORT}\" --expose-network --max-parallel-jobs \"${NEMOFOLD_MAX_PARALLEL_JOBS}\""]
