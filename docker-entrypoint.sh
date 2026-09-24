#!/bin/sh
set -eu

HYBRID_HOST="${HYBRID_HOST:-127.0.0.1}"
HYBRID_PORT="${HYBRID_PORT:-5002}"
HYBRID_STARTUP_TIMEOUT="${HYBRID_STARTUP_TIMEOUT:-600}"
export HYBRID_HEALTH_URL="http://${HYBRID_HOST}:${HYBRID_PORT}/health"

echo "[entrypoint] starting Hybrid OCR service on ${HYBRID_HOST}:${HYBRID_PORT}"
opendataloader-pdf-hybrid \
  --host "${HYBRID_HOST}" \
  --port "${HYBRID_PORT}" \
  --force-ocr \
  --ocr-lang "${HYBRID_OCR_LANG:-ch_sim,en}" \
  --enrich-picture-description &
HYBRID_PID=$!

cleanup() {
  kill "${HYBRID_PID}" 2>/dev/null || true
  wait "${HYBRID_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

elapsed=0
while [ "${elapsed}" -lt "${HYBRID_STARTUP_TIMEOUT}" ]; do
  if python -c 'import os, urllib.request; urllib.request.urlopen(os.environ["HYBRID_HEALTH_URL"], timeout=2)' >/dev/null 2>&1; then
    echo "[entrypoint] Hybrid OCR service is healthy"
    break
  fi
  if ! kill -0 "${HYBRID_PID}" 2>/dev/null; then
    echo "[entrypoint] Hybrid OCR service exited during startup" >&2
    exit 1
  fi
  sleep 1
  elapsed=$((elapsed + 1))
done

if [ "${elapsed}" -ge "${HYBRID_STARTUP_TIMEOUT}" ]; then
  echo "[entrypoint] Hybrid OCR service did not become healthy within ${HYBRID_STARTUP_TIMEOUT}s" >&2
  exit 1
fi

echo "[entrypoint] starting PDF API on 0.0.0.0:8000"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info &
API_PID=$!
wait "${API_PID}"
