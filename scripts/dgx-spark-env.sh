#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${REPO_ROOT}/.env.dgx-spark"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Missing ${CONFIG_FILE}. Copy .env.dgx-spark.example first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${CONFIG_FILE}"
set +a

if [[ -z "${NGC_API_KEY:-}" ]]; then
  echo "NGC_API_KEY is required in .env.dgx-spark." >&2
  exit 1
fi

cd "${REPO_ROOT}"

# Load upstream defaults, then force every model endpoint onto the local network.
# shellcheck disable=SC1091
source deploy/compose/.env
# shellcheck disable=SC1091
source deploy/dgx-spark/local-models.env
# Reapply deployment-specific values so .env.dgx-spark is the final authority.
# shellcheck disable=SC1090
source "${CONFIG_FILE}"

export TAG="${TAG:-2.6.0}"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-nvidia-rag-dgx-spark}"
export COMPOSE_IGNORE_ORPHANS=true
export NV_INGEST_VERSION="${NV_INGEST_VERSION:-26.3.0}"
export NV_INGEST_SOURCE_DIR="${NV_INGEST_SOURCE_DIR:-${REPO_ROOT}/.sources/nemo-retriever-${NV_INGEST_VERSION}}"
export NEMOTRON_OCR_SOURCE_DIR="${NEMOTRON_OCR_SOURCE_DIR:-${REPO_ROOT}/.sources/nemotron-ocr-v1}"

docker_cmd() {
  if [[ "${DGX_SPARK_DOCKER_SUDO:-false}" != "true" ]]; then
    docker "$@"
    return
  fi

  sudo bash -c '
    set -euo pipefail
    config_file="$1"
    repo_root="$2"
    shift 2

    cd "${repo_root}"
    set -a
    source "${config_file}"
    source deploy/compose/.env
    source deploy/dgx-spark/local-models.env
    source "${config_file}"
    set +a
    export COMPOSE_IGNORE_ORPHANS=true
    export NV_INGEST_VERSION="${NV_INGEST_VERSION:-26.3.0}"
    export NV_INGEST_SOURCE_DIR="${NV_INGEST_SOURCE_DIR:-${repo_root}/.sources/nemo-retriever-${NV_INGEST_VERSION}}"
    export NEMOTRON_OCR_SOURCE_DIR="${NEMOTRON_OCR_SOURCE_DIR:-${repo_root}/.sources/nemotron-ocr-v1}"

    exec docker "$@"
  ' bash "${CONFIG_FILE}" "${REPO_ROOT}" "$@"
}
