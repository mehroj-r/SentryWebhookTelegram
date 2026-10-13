FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/data.db

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first so code changes don't invalidate this layer.
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml --extra postgres

COPY alembic.ini main.py ./
COPY migrations ./migrations
COPY src ./src

RUN useradd --system --uid 10001 --no-create-home app \
    && mkdir /data && chown app /data
USER app
VOLUME ["/data"]

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)" || exit 1

CMD ["python", "main.py"]
