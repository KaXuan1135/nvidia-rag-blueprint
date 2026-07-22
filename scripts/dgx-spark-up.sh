#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/dgx-spark-env.sh"

RAG_COMPOSE=(
  -f deploy/compose/docker-compose-rag-server.yaml
  -f deploy/dgx-spark/compose.rag-arm64.yaml
  -f deploy/dgx-spark/compose.personas.yaml
)
NIMS_COMPOSE=(
  -f deploy/dgx-spark/compose.nims-local.yaml
)
INGEST_COMPOSE=(
  -f deploy/compose/docker-compose-ingestor-server.yaml
  -f deploy/dgx-spark/compose.ingestor-arm64.yaml
)

"${SCRIPT_DIR}/dgx-spark-fetch-sources.sh"

wait_for_http() {
  local service_name="$1"
  local url="$2"
  local attempts=60

  echo "Waiting for ${service_name}..."
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl --fail --silent --show-error --max-time 5 "${url}" >/dev/null 2>&1; then
      echo "${service_name} is ready."
      return
    fi
    sleep 5
  done

  echo "${service_name} did not become ready within 5 minutes." >&2
  exit 1
}

docker_cmd compose -f deploy/compose/vectordb.yaml config --quiet
docker_cmd compose "${NIMS_COMPOSE[@]}" config --quiet
docker_cmd compose "${INGEST_COMPOSE[@]}" config --quiet
docker_cmd compose "${RAG_COMPOSE[@]}" config --quiet

# --no-build and pull_policy: never prevent fallback to NVIDIA's incompatible
# linux/amd64 application images.
docker_cmd compose -f deploy/compose/vectordb.yaml up -d
echo "Starting local NVIDIA NIMs. The first model download can take a long time."
docker_cmd compose "${NIMS_COMPOSE[@]}" up -d \
  --wait \
  --wait-timeout "${LOCAL_NIM_STARTUP_TIMEOUT:-3600}"

docker_cmd compose "${INGEST_COMPOSE[@]}" up -d --no-build
wait_for_http "Ingestion API" "http://localhost:8082/v1/health?check_dependencies=true"

docker_cmd compose "${RAG_COMPOSE[@]}" up -d --no-build rag-server rag-server-customer
wait_for_http "Internal RAG API" "http://localhost:8081/v1/health?check_dependencies=true"
wait_for_http "Customer RAG API" "http://localhost:8083/v1/health?check_dependencies=true"

docker_cmd compose "${RAG_COMPOSE[@]}" up -d --no-build rag-frontend customer-frontend

echo "NVIDIA RAG Blueprint is ready."
echo "Internal UI: http://localhost:8090"
echo "Customer UI: http://localhost:8091"
echo "Run ./scripts/dgx-spark-status.sh to inspect service state."
