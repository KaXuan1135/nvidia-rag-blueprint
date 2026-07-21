#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/dgx-spark-env.sh"

NIMS_COMPOSE=(
  -f deploy/dgx-spark/compose.nims-local.yaml
)

docker_cmd compose "${NIMS_COMPOSE[@]}" config --quiet

echo "Pulling local NVIDIA NIM images. Model weights download when NIMs first start."
docker_cmd compose "${NIMS_COMPOSE[@]}" pull --ignore-buildable
