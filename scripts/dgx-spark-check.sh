#!/usr/bin/env bash

set -uo pipefail

failures=0
warnings=0

pass() {
  echo "PASS: $1"
}

warn() {
  echo "WARN: $1"
  warnings=$((warnings + 1))
}

fail() {
  echo "FAIL: $1"
  failures=$((failures + 1))
}

architecture="$(uname -m)"
if [[ "${architecture}" == "aarch64" || "${architecture}" == "arm64" ]]; then
  pass "ARM64 host detected (${architecture})"
else
  warn "Expected DGX Spark ARM64 host, found ${architecture}"
fi

available_kb="$(df -Pk . | awk 'NR == 2 {print $4}')"
if [[ -n "${available_kb}" && "${available_kb}" -ge 209715200 ]]; then
  pass "At least 200 GB disk space is available"
else
  fail "Local NIM images and model caches require at least 200 GB free disk space"
fi

if command -v docker >/dev/null 2>&1; then
  pass "Docker CLI is installed"
else
  fail "Docker CLI is not installed"
fi

if docker compose version >/dev/null 2>&1; then
  compose_version="$(docker compose version --short 2>/dev/null || true)"
  pass "Docker Compose is available (${compose_version:-version unknown})"
else
  fail "Docker Compose plugin is unavailable"
fi

if command -v git >/dev/null 2>&1; then
  pass "Git is installed"
else
  fail "Git is required to fetch pinned NVIDIA source"
fi

if command -v git-lfs >/dev/null 2>&1; then
  pass "Git LFS is installed"
else
  fail "Git LFS is required to fetch Nemotron OCR checkpoints"
fi

if docker info >/dev/null 2>&1; then
  pass "Docker daemon is reachable by the current user"
else
  warn "Docker daemon is not reachable; Docker group membership or sudo may be required"
fi

if [[ -r /proc/driver/nvidia/version ]]; then
  driver_version="$(awk '/NVRM version/ {print $8; exit}' /proc/driver/nvidia/version)"
  pass "NVIDIA driver is loaded (${driver_version:-version unknown})"
else
  warn "Could not read the loaded NVIDIA driver version"
fi

echo "Summary: ${failures} failure(s), ${warnings} warning(s)"
exit "${failures}"
