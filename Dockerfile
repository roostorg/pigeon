FROM python:3.12-slim AS builder

ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY modelspecs ./modelspecs
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime

ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PIGEON_HOST=0.0.0.0 \
    PIGEON_PORT=8900 \
    PIGEON_MODELSPECS_DIR=/app/modelspecs \
    PIGEON_DB_PATH=/var/lib/pigeon/pigeon.db

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/modelspecs /app/modelspecs

RUN addgroup --system pigeon && adduser --system --ingroup pigeon pigeon \
    && mkdir -p /var/lib/pigeon \
    && chown -R pigeon:pigeon /app /var/lib/pigeon

USER pigeon
EXPOSE 8900
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8900/health', timeout=3)"]
CMD ["pigeon"]
