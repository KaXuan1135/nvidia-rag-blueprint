#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/dgx-spark-env.sh"

"${SCRIPT_DIR}/dgx-spark-fetch-sources.sh"

RAG_COMPOSE=(
  -f deploy/compose/docker-compose-rag-server.yaml
  -f deploy/dgx-spark/compose.rag-arm64.yaml
  -f deploy/dgx-spark/compose.personas.yaml
)
INGEST_COMPOSE=(
  -f deploy/compose/docker-compose-ingestor-server.yaml
  -f deploy/dgx-spark/compose.ingestor-arm64.yaml
)
NIMS_COMPOSE=(
  -f deploy/dgx-spark/compose.nims-local.yaml
)

docker_cmd compose "${RAG_COMPOSE[@]}" build rag-server rag-frontend customer-frontend
docker_cmd compose "${INGEST_COMPOSE[@]}" build ingestor-server nv-ingest-ms-runtime
docker_cmd compose "${NIMS_COMPOSE[@]}" build nemotron-ocr

echo "Native ARM64 application images built successfully."
