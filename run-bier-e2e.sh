#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NDN_CXX_DIR="${ROOT_DIR}/ndn-cxx"
NFD_DIR="${ROOT_DIR}/NFD"
MINI_NDN_DIR="${ROOT_DIR}/mini-ndn"
MINI_NDN_SCENARIO="${MINI_NDN_DIR}/examples/bier_multicast_experiment.py"
OS_NAME="$(uname -s)"

JOBS="${JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)}"
BUILD_TYPE="${BUILD_TYPE:-debug}"
RUN_MININDN=1
RUN_INSTALL=1
RUN_UNIT_TESTS=1

usage() {
  cat <<'EOF'
Usage: ./run-bier-e2e.sh [options]

Options:
  --no-install         Build/test only (skip sudo waf install)
  --no-unit-tests      Build/install only (skip unit test binaries)
  --no-minindn         Skip Mini-NDN scenario run
  -j, --jobs <N>       Parallel build jobs (default: auto)
  -h, --help           Show this help

Environment variables:
  JOBS=<N>             Same as --jobs
  BUILD_TYPE=debug     or release; passed to waf configure
EOF
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

append_path() {
  local value="$1"
  local current="${!2:-}"
  if [[ -z "${value}" ]]; then
    return
  fi
  if [[ -z "${current}" ]]; then
    printf -v "$2" '%s' "${value}"
  else
    printf -v "$2" '%s:%s' "${value}" "${current}"
  fi
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
require_cmd pkg-config
require_cmd clang++

if [[ ! -d "${NDN_CXX_DIR}" || ! -d "${NFD_DIR}" || ! -d "${MINI_NDN_DIR}" ]]; then
  echo "ERROR: expected ndn-cxx, NFD, mini-ndn under ${ROOT_DIR}"
  exit 1
fi

WAF_BUILD_FLAGS=()
if [[ "${BUILD_TYPE}" == "debug" ]]; then
  WAF_BUILD_FLAGS+=(--debug)
fi

if [[ "${OS_NAME}" == "Darwin" ]]; then
  if command -v brew >/dev/null 2>&1 && [[ -d "$(brew --prefix boost 2>/dev/null || true)" ]]; then
    BOOST_PREFIX="$(brew --prefix boost)"
    WAF_BUILD_FLAGS+=(--boost-includes="${BOOST_PREFIX}/include" --boost-libs="${BOOST_PREFIX}/lib")
  fi
  # Boost 1.90 headers trigger -Wextra-semi under strict -Werror builds with clang.
  export CXXFLAGS="${CXXFLAGS:-} -Wno-error=extra-semi -Wno-extra-semi"
fi

append_path "/usr/local/lib/pkgconfig" PKG_CONFIG_PATH
append_path "/opt/homebrew/lib/pkgconfig" PKG_CONFIG_PATH
append_path "/opt/local/lib/pkgconfig" PKG_CONFIG_PATH
export PKG_CONFIG_PATH

echo "=== Stage 1: Build ndn-cxx ==="
run bash -lc "cd '${NDN_CXX_DIR}' && ./waf configure --with-tests ${WAF_BUILD_FLAGS[*]}"
run bash -lc "cd '${NDN_CXX_DIR}' && ./waf -j${JOBS}"
if [[ "${RUN_INSTALL}" -eq 1 ]]; then
  require_cmd sudo
  run bash -lc "cd '${NDN_CXX_DIR}' && sudo ./waf install"
  if [[ "${OS_NAME}" == "Linux" ]]; then
    run sudo ldconfig
  fi
fi
if [[ "${RUN_UNIT_TESTS}" -eq 1 ]]; then
  if [[ "${RUN_INSTALL}" -eq 1 ]]; then
    run bash -lc "cd '${NDN_CXX_DIR}' && ./build/unit-tests -t 'Lp/TestPacket/EncodeDecodeBierBitString'"
    run bash -lc "cd '${NDN_CXX_DIR}' && ./build/unit-tests -t 'TestFace/ExpressInterest/InterestTagRoundtrip'"
  else
    run bash -lc "cd '${NDN_CXX_DIR}' && DYLD_LIBRARY_PATH='${NDN_CXX_DIR}/build:\${DYLD_LIBRARY_PATH:-}' LD_LIBRARY_PATH='${NDN_CXX_DIR}/build:\${LD_LIBRARY_PATH:-}' ./build/unit-tests -t 'Lp/TestPacket/EncodeDecodeBierBitString'"
    run bash -lc "cd '${NDN_CXX_DIR}' && DYLD_LIBRARY_PATH='${NDN_CXX_DIR}/build:\${DYLD_LIBRARY_PATH:-}' LD_LIBRARY_PATH='${NDN_CXX_DIR}/build:\${LD_LIBRARY_PATH:-}' ./build/unit-tests -t 'TestFace/ExpressInterest/InterestTagRoundtrip'"
  fi
fi

echo "=== Stage 2: Build NFD ==="
run bash -lc "cd '${NFD_DIR}' && ./waf configure --with-tests ${WAF_BUILD_FLAGS[*]}"
run bash -lc "cd '${NFD_DIR}' && ./waf -j${JOBS}"
if [[ "${RUN_INSTALL}" -eq 1 ]]; then
  run bash -lc "cd '${NFD_DIR}' && sudo ./waf install"
  if [[ "${OS_NAME}" == "Linux" ]]; then
    run sudo ldconfig
  fi
fi
if [[ "${RUN_UNIT_TESTS}" -eq 1 ]]; then
  if [[ "${RUN_INSTALL}" -eq 1 ]]; then
    run bash -lc "cd '${NFD_DIR}' && ./build/unit-tests-daemon -t 'Fw/TestForwarder/BierReplicationPrePit'"
    run bash -lc "cd '${NFD_DIR}' && ./build/unit-tests-daemon -t 'Fw/TestForwarder/BierLocalFallbackToNdnPipeline'"
    run bash -lc "cd '${NFD_DIR}' && ./build/unit-tests-daemon -t 'Fw/TestForwarder/BierRuntimeControlInterests'"
    run bash -lc "cd '${NFD_DIR}' && ./build/unit-tests-daemon -t 'Fw/TestForwarder/ProcessConfig/BierConfig'"
    run bash -lc "cd '${NFD_DIR}' && ./build/unit-tests-daemon -t 'Face/TestGenericLinkService/LpFields/SendBierBitStringInterest'"
    run bash -lc "cd '${NFD_DIR}' && ./build/unit-tests-daemon -t 'Face/TestGenericLinkService/LpFields/ReceiveBierBitStringInterest'"
  else
    run bash -lc "cd '${NFD_DIR}' && DYLD_LIBRARY_PATH='${NFD_DIR}/build:${NDN_CXX_DIR}/build:\${DYLD_LIBRARY_PATH:-}' LD_LIBRARY_PATH='${NFD_DIR}/build:${NDN_CXX_DIR}/build:\${LD_LIBRARY_PATH:-}' ./build/unit-tests-daemon -t 'Fw/TestForwarder/BierReplicationPrePit'"
    run bash -lc "cd '${NFD_DIR}' && DYLD_LIBRARY_PATH='${NFD_DIR}/build:${NDN_CXX_DIR}/build:\${DYLD_LIBRARY_PATH:-}' LD_LIBRARY_PATH='${NFD_DIR}/build:${NDN_CXX_DIR}/build:\${LD_LIBRARY_PATH:-}' ./build/unit-tests-daemon -t 'Fw/TestForwarder/BierLocalFallbackToNdnPipeline'"
    run bash -lc "cd '${NFD_DIR}' && DYLD_LIBRARY_PATH='${NFD_DIR}/build:${NDN_CXX_DIR}/build:\${DYLD_LIBRARY_PATH:-}' LD_LIBRARY_PATH='${NFD_DIR}/build:${NDN_CXX_DIR}/build:\${LD_LIBRARY_PATH:-}' ./build/unit-tests-daemon -t 'Fw/TestForwarder/BierRuntimeControlInterests'"
    run bash -lc "cd '${NFD_DIR}' && DYLD_LIBRARY_PATH='${NFD_DIR}/build:${NDN_CXX_DIR}/build:\${DYLD_LIBRARY_PATH:-}' LD_LIBRARY_PATH='${NFD_DIR}/build:${NDN_CXX_DIR}/build:\${LD_LIBRARY_PATH:-}' ./build/unit-tests-daemon -t 'Fw/TestForwarder/ProcessConfig/BierConfig'"
    run bash -lc "cd '${NFD_DIR}' && DYLD_LIBRARY_PATH='${NFD_DIR}/build:${NDN_CXX_DIR}/build:\${DYLD_LIBRARY_PATH:-}' LD_LIBRARY_PATH='${NFD_DIR}/build:${NDN_CXX_DIR}/build:\${LD_LIBRARY_PATH:-}' ./build/unit-tests-daemon -t 'Face/TestGenericLinkService/LpFields/SendBierBitStringInterest'"
    run bash -lc "cd '${NFD_DIR}' && DYLD_LIBRARY_PATH='${NFD_DIR}/build:${NDN_CXX_DIR}/build:\${DYLD_LIBRARY_PATH:-}' LD_LIBRARY_PATH='${NFD_DIR}/build:${NDN_CXX_DIR}/build:\${LD_LIBRARY_PATH:-}' ./build/unit-tests-daemon -t 'Face/TestGenericLinkService/LpFields/ReceiveBierBitStringInterest'"
  fi
fi

if [[ "${RUN_MININDN}" -eq 1 ]]; then
  echo "=== Stage 3: Mini-NDN BIER experiment ==="
  if [[ "${OS_NAME}" != "Linux" ]]; then
    echo "WARNING: Mini-NDN runtime is Linux-centric; skipping scenario on ${OS_NAME}."
    echo "         Run this stage on Linux:"
    echo "         sudo -E python3 '${MINI_NDN_SCENARIO}'"
  else
    run python3 -m py_compile "${MINI_NDN_SCENARIO}"
    run bash -lc "cd '${MINI_NDN_DIR}' && ./install.sh --source --use-existing -y"
    run sudo -E python3 "${MINI_NDN_SCENARIO}"
  fi
fi

echo
echo "All requested stages completed."
