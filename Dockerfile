FROM python:3.11-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.7.19 /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless poppler-utils libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

ENV PATH="/app/.venv/bin:$PATH"

ARG PRELOAD_HYBRID_MODELS=1
ENV HF_HOME="/opt/hybrid-models/huggingface" \
    EASYOCR_MODULE_PATH="/opt/hybrid-models/easyocr" \
    DOCLING_ARTIFACTS_PATH="/opt/hybrid-models/docling"
RUN --mount=type=cache,id=hybrid-models,target=/root/.cache,sharing=locked \
    set -eu; \
    mkdir -p "$HF_HOME" "$EASYOCR_MODULE_PATH" "$DOCLING_ARTIFACTS_PATH" \
        /root/.cache/huggingface /root/.cache/docling \
    && if [ "$PRELOAD_HYBRID_MODELS" = "1" ]; then \
         echo "Downloading Hybrid models into the image"; \
         docling-tools models download layout tableformer easyocr smolvlm \
           --easyocr-lang ch_sim --output-dir /root/.cache/docling; \
         cp -a /root/.cache/docling/. "$DOCLING_ARTIFACTS_PATH/"; \
       else \
         echo "Skipping Hybrid model preload (PRELOAD_HYBRID_MODELS=$PRELOAD_HYBRID_MODELS)"; \
       fi

ENV HF_HUB_OFFLINE="1"

# Exercise the real Hybrid pipeline without network or the download cache mount.
# Keep this before app code so normal API changes reuse the verified model layer.
COPY scripts/verify_hybrid_models.py ./scripts/verify_hybrid_models.py
RUN --network=none if [ "$PRELOAD_HYBRID_MODELS" = "1" ]; then \
      timeout 600 python -u scripts/verify_hybrid_models.py; \
    fi

COPY app ./app
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
RUN mkdir -p /app/output

EXPOSE 8000
EXPOSE 5002
ENTRYPOINT ["/app/docker-entrypoint.sh"]
