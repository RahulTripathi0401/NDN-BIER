#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NDND_DIR="${ROOT_DIR}/ndnd"
MINI_NDN_DIR="${ROOT_DIR}/mini-ndn"
OS_NAME="$(uname -s)"

JOBS="${JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)}"
BUILD_TYPE="${BUILD_TYPE:-debug}"
RUN_MININDN=1
RUN_INSTALL=1
RUN_UNIT_TESTS=1

usage() {
  cat <<'INNER_EOF'
Usage: ./run-bier-e2e.sh [options]

Options:
  --no-install         Build/test only (skip sudo install)
  --no-unit-tests      Build/install only (skip unit tests)
  --no-minindn         Skip Mini-NDN scenario run
  -j, --jobs <N>       Parallel build jobs (default: auto)
  -h, --help           Show this help

Environment variables:
  JOBS=<N>             Same as --jobs
  BUILD_TYPE=debug     or release; controls build optimizations
INNER_EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: missing command '$1'"
    exit 1
  fi
}

run() {
  echo
  echo ">>> $*"
  "$@"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-install)
      RUN_INSTALL=0
      shift
      ;;
    --no-unit-tests)
      RUN_UNIT_TESTS=0
      shift
      ;;
    --no-minindn)
      RUN_MININDN=0
      shift
      ;;
    -j|--jobs)
      JOBS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown option '$1'"
      usage
      exit 1
      ;;
  esac
done

require_cmd python3
require_cmd go

if [[ ! -d "${NDND_DIR}" || ! -d "${MINI_NDN_DIR}" ]]; then
  echo "ERROR: expected ndnd, mini-ndn under ${ROOT_DIR}"
  exit 1
fi

echo "=== Stage 1: Build ndnd (Go) ==="
run bash -lc "cd '${NDND_DIR}' && go build -v ./..."

if [[ "${RUN_UNIT_TESTS}" -eq 1 ]]; then
  echo "=== Stage 2: Run ndnd unit tests ==="
  run bash -lc "cd '${NDND_DIR}' && go test -v ./fw/fw -run TestBier"
fi

if [[ "${RUN_INSTALL}" -eq 1 ]]; then
  echo "=== Stage 3: Install ndnd ==="
  require_cmd sudo
  if [ ! -f "${NDND_DIR}/.bin/ndnd" ]; then
    echo ">>> bash -lc cd '${NDND_DIR}' && go build -v -o /usr/local/bin/ndnd ./cmd/ndnd"
    run bash -lc "cd '${NDND_DIR}' && sudo env PATH=\"\$PATH\" go build -v -o /usr/local/bin/ndnd ./cmd/ndnd"
    run bash -lc "cd '${NDND_DIR}' && sudo env PATH=\"\$PATH\" go build -v -o /usr/local/bin/svs-chat ./cmd/svs-chat/main.go"
  else
    echo "Skipping Go build (pre-built binary present)"
    run bash -lc "sudo cp '${NDND_DIR}/.bin/ndnd' /usr/local/bin/ndnd"
    if [ -f "${NDND_DIR}/.bin/svs-chat" ]; then
      run bash -lc "sudo cp '${NDND_DIR}/.bin/svs-chat' /usr/local/bin/svs-chat"
    fi
  fi
  echo "ndnd and svs-chat installed to /usr/local/bin/"
fi

if [[ "${RUN_MININDN}" -eq 1 ]]; then
  echo "=== Stage 4: Mini-NDN BIER experiment ==="
  if [[ "${OS_NAME}" != "Linux" ]]; then
    echo "WARNING: Mini-NDN runtime is Linux-centric; skipping scenario on ${OS_NAME}."
    echo "         Run this script inside a Linux container or VM."
  else
    run bash -lc "cd '${MINI_NDN_DIR}' && ./install.sh --source --use-existing -y"
    run bash -lc "cd '${NDND_DIR}' && sudo env PATH=\"\$PATH\" make e2e"
    
    echo "=== Extracting Logs ==="
    mkdir -p "${ROOT_DIR}/logs"
    sudo cp -r /tmp/minindn "${ROOT_DIR}/logs/" 2>/dev/null || true
    sudo cp /tmp/bier-*.log "${ROOT_DIR}/logs/" 2>/dev/null || true
    sudo chown -R 1000:1000 "${ROOT_DIR}/logs/" 2>/dev/null || true
    echo "Logs saved to ${ROOT_DIR}/logs"
  fi
fi

echo
echo "All requested stages completed."
