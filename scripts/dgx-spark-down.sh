#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/dgx-spark-env.sh"

docker_cmd compose \
  -f deploy/compose/vectordb.yaml \
  -f deploy/compose/docker-compose-ingestor-server.yaml \
  -f deploy/dgx-spark/compose.ingestor-arm64.yaml \
  -f deploy/compose/docker-compose-rag-server.yaml \
  -f deploy/dgx-spark/compose.rag-arm64.yaml \
  -f deploy/dgx-spark/compose.personas.yaml \
  -f deploy/dgx-spark/compose.nims-local.yaml \
  down
