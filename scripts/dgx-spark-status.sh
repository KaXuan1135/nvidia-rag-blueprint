#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/dgx-spark-env.sh"

docker_cmd ps -a \
  --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
  --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
