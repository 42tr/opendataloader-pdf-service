FROM python:3.11-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.7.19 /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

ENV PATH="/app/.venv/bin:$PATH"

ARG PRELOAD_HYBRID_MODELS=1
ENV HF_HOME="/opt/hybrid-models/huggingface" \
    EASYOCR_MODULE_PATH="/opt/hybrid-models/easyocr"
RUN mkdir -p "$HF_HOME" "$EASYOCR_MODULE_PATH" \
    && if [ "$PRELOAD_HYBRID_MODELS" = "1" ]; then \
         echo "Downloading Hybrid models into the image"; \
         python -c 'from huggingface_hub import snapshot_download; snapshot_download(repo_id="HuggingFaceTB/SmolVLM-256M-Instruct")'; \
         python -c 'import easyocr; easyocr.Reader(["ch_sim"], gpu=False, model_storage_directory="/opt/hybrid-models/easyocr", download_enabled=True)'; \
       else \
         echo "Skipping Hybrid model preload (PRELOAD_HYBRID_MODELS=$PRELOAD_HYBRID_MODELS)"; \
       fi

ENV HF_HUB_OFFLINE="1"

COPY app ./app
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
RUN mkdir -p /app/output

EXPOSE 8000
EXPOSE 5002
ENTRYPOINT ["/app/docker-entrypoint.sh"]
