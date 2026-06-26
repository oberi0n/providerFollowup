#!/bin/sh
set -eu

: "${OLLAMA_HOST:=http://ollama:11434}"
: "${OLLAMA_MODEL:=qwen2.5:0.5b}"
: "${OLLAMA_WAIT_SECONDS:=180}"

export OLLAMA_HOST

started_at=$(date +%s)
echo "Waiting for Ollama at ${OLLAMA_HOST}..."
until ollama list >/dev/null 2>&1; do
  now=$(date +%s)
  if [ $((now - started_at)) -ge "$OLLAMA_WAIT_SECONDS" ]; then
    echo "Ollama did not become ready within ${OLLAMA_WAIT_SECONDS}s" >&2
    exit 1
  fi
  sleep 2
done

echo "Ensuring lightweight OCR interpretation model is available: ${OLLAMA_MODEL}"
ollama pull "$OLLAMA_MODEL"
ollama list
