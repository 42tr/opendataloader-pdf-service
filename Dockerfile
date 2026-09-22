FROM python:3.11-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.7.19 /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
RUN mkdir -p /app/output

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
EXPOSE 5002
ENTRYPOINT ["/app/docker-entrypoint.sh"]
