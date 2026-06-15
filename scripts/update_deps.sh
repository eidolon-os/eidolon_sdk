#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/update_deps.sh [options] [project ...]

Build the latest eidolon-sdk wheel and install it into sibling project venvs.

Options:
  --with-deps          Let pip install/upgrade eidolon-sdk dependencies too.
                       Default is --no-deps to avoid unexpectedly changing
                       sibling project dependency versions.
  --extras EXTRAS      Extras to install when --with-deps is used.
                       Default: db
  --dist-dir DIR       Wheel output directory.
                       Default: <eidolon_sdk>/dist/sdk-update
  --help              Show this help.

Projects default to:
  eidolon_admin eidolon_agent eidolon_channel eidolon_hub eidolon_memory

Examples:
  scripts/update_deps.sh
  scripts/update_deps.sh --with-deps eidolon_admin eidolon_agent
  scripts/update_deps.sh --with-deps --extras db,dev eidolon_admin
EOF
}

SDK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_DIR="$(cd "${SDK_DIR}/.." && pwd)"
SDK_PYTHON="${SDK_DIR}/.venv/bin/python"
DIST_DIR="${SDK_DIR}/dist/sdk-update"
INSTALL_DEPS=0
EXTRAS="db"
PROJECTS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-deps)
      INSTALL_DEPS=1
      shift
      ;;
    --extras)
      if [[ $# -lt 2 ]]; then
        echo "error: --extras requires a value" >&2
        exit 2
      fi
      EXTRAS="$2"
      shift 2
      ;;
    --dist-dir)
      if [[ $# -lt 2 ]]; then
        echo "error: --dist-dir requires a value" >&2
        exit 2
      fi
      DIST_DIR="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --*)
      echo "error: unknown option $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      PROJECTS+=("$1")
      shift
      ;;
  esac
done

if [[ ${#PROJECTS[@]} -eq 0 ]]; then
  PROJECTS=(
    eidolon_admin
    eidolon_agent
    eidolon_channel
    eidolon_hub
    eidolon_memory
  )
fi

if [[ ! -x "${SDK_PYTHON}" ]]; then
  echo "error: missing SDK venv python: ${SDK_PYTHON}" >&2
  echo "create it first, then install SDK build/dev dependencies" >&2
  exit 1
fi

echo "==> Building eidolon-sdk wheel"
rm -rf "${DIST_DIR}"
mkdir -p "${DIST_DIR}"
BUILD_ARGS=(--no-deps --wheel-dir "${DIST_DIR}")
if "${SDK_PYTHON}" -c "import hatchling" >/dev/null 2>&1; then
  BUILD_ARGS=(--no-build-isolation "${BUILD_ARGS[@]}")
fi
"${SDK_PYTHON}" -m pip wheel "${BUILD_ARGS[@]}" "${SDK_DIR}"

shopt -s nullglob
WHEELS=("${DIST_DIR}"/eidolon_sdk-*.whl)
shopt -u nullglob
if [[ ${#WHEELS[@]} -eq 0 ]]; then
  echo "error: wheel build did not produce eidolon_sdk-*.whl in ${DIST_DIR}" >&2
  exit 1
fi
WHEEL="${WHEELS[0]}"
echo "==> Built ${WHEEL}"

if [[ "${INSTALL_DEPS}" -eq 1 && -n "${EXTRAS}" ]]; then
  INSTALL_TARGET="${WHEEL}[${EXTRAS}]"
  PIP_DEP_ARGS=()
else
  INSTALL_TARGET="${WHEEL}"
  PIP_DEP_ARGS=(--no-deps)
fi

for project in "${PROJECTS[@]}"; do
  project_dir="${ROOT_DIR}/${project}"
  python_bin="${project_dir}/.venv/bin/python"
  if [[ ! -x "${python_bin}" ]]; then
    echo "==> Skipping ${project}: missing ${python_bin}"
    continue
  fi

  echo "==> Updating ${project}"
  if ! "${python_bin}" -m pip --version >/dev/null 2>&1; then
    echo "    pip not found in ${project}; bootstrapping with ensurepip"
    "${python_bin}" -m ensurepip --upgrade >/dev/null
  fi
  "${python_bin}" -m pip install --upgrade --force-reinstall "${PIP_DEP_ARGS[@]}" "${INSTALL_TARGET}"
done

echo "==> Done"
