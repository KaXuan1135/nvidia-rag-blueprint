#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

NV_INGEST_VERSION="${NV_INGEST_VERSION:-26.3.0}"
NV_INGEST_COMMIT="${NV_INGEST_COMMIT:-b1aa9729809bd46c0b4f089ccd0ead946303eba3}"
NV_INGEST_SOURCE_DIR="${NV_INGEST_SOURCE_DIR:-${REPO_ROOT}/.sources/nemo-retriever-${NV_INGEST_VERSION}}"
NEMOTRON_OCR_COMMIT="${NEMOTRON_OCR_COMMIT:-8657d08d3279f4864002d5fd3fdcd47ad8c96bcb}"
NEMOTRON_OCR_SOURCE_DIR="${NEMOTRON_OCR_SOURCE_DIR:-${REPO_ROOT}/.sources/nemotron-ocr-v1}"

if [[ ! -d "${NV_INGEST_SOURCE_DIR}/.git" ]]; then
  mkdir -p "$(dirname "${NV_INGEST_SOURCE_DIR}")"
  git clone \
    --depth 1 \
    --branch "${NV_INGEST_VERSION}" \
    https://github.com/NVIDIA/NeMo-Retriever.git \
    "${NV_INGEST_SOURCE_DIR}"
fi

actual_commit="$(git -C "${NV_INGEST_SOURCE_DIR}" rev-parse HEAD)"
if [[ "${actual_commit}" != "${NV_INGEST_COMMIT}" ]]; then
  echo "Unexpected NeMo Retriever commit: ${actual_commit}" >&2
  echo "Expected: ${NV_INGEST_COMMIT}" >&2
  exit 1
fi

if [[ ! -d "${NEMOTRON_OCR_SOURCE_DIR}/.git" ]]; then
  mkdir -p "$(dirname "${NEMOTRON_OCR_SOURCE_DIR}")"
  git init "${NEMOTRON_OCR_SOURCE_DIR}"
  git -C "${NEMOTRON_OCR_SOURCE_DIR}" remote add origin \
    https://huggingface.co/nvidia/nemotron-ocr-v1
  git -C "${NEMOTRON_OCR_SOURCE_DIR}" fetch --depth 1 origin "${NEMOTRON_OCR_COMMIT}"
  git -C "${NEMOTRON_OCR_SOURCE_DIR}" checkout --detach FETCH_HEAD
fi

actual_ocr_commit="$(git -C "${NEMOTRON_OCR_SOURCE_DIR}" rev-parse HEAD)"
if [[ "${actual_ocr_commit}" != "${NEMOTRON_OCR_COMMIT}" ]]; then
  echo "Unexpected Nemotron OCR commit: ${actual_ocr_commit}" >&2
  echo "Expected: ${NEMOTRON_OCR_COMMIT}" >&2
  exit 1
fi

checkpoints_ready=true
for checkpoint in detector.pth recognizer.pth relational.pth; do
  checkpoint_path="${NEMOTRON_OCR_SOURCE_DIR}/checkpoints/${checkpoint}"
  if [[ ! -f "${checkpoint_path}" || "$(wc -c < "${checkpoint_path}")" -lt 1000000 ]]; then
    checkpoints_ready=false
    break
  fi
done

if [[ "${checkpoints_ready}" != "true" ]]; then
  if ! command -v git-lfs >/dev/null 2>&1; then
    echo "git-lfs is required to download the Nemotron OCR checkpoints." >&2
    exit 1
  fi
  git -C "${NEMOTRON_OCR_SOURCE_DIR}" lfs pull --include="checkpoints/**"
fi

for checkpoint in detector.pth recognizer.pth relational.pth; do
  checkpoint_path="${NEMOTRON_OCR_SOURCE_DIR}/checkpoints/${checkpoint}"
  if [[ ! -f "${checkpoint_path}" || "$(wc -c < "${checkpoint_path}")" -lt 1000000 ]]; then
    echo "Nemotron OCR checkpoint is missing or still an LFS pointer: ${checkpoint}" >&2
    exit 1
  fi
done

echo "NeMo Retriever ${NV_INGEST_VERSION} source ready at ${NV_INGEST_SOURCE_DIR}"
echo "Nemotron OCR v1 source ready at ${NEMOTRON_OCR_SOURCE_DIR}"
