#!/usr/bin/env bash
# Regenerate the gRPC bindings the Contract Plane publishes.
#
# The .proto under contracts/grpc is the single copy of each cross-project wire
# contract; consumers import the generated bindings from eidolon_sdk rather than
# mirroring the .proto and generating their own.
#
# Generated files are committed: a release ships exact Git commits, so anything
# absent from Git is absent from the release, and the target build is offline
# with no grpcio-tools available.
#
#   ./scripts/gen_grpc_stubs.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROTO_ROOT="$ROOT/contracts/grpc"
OUT_ROOT="$ROOT/eidolon_sdk/grpc"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="python3"
fi

mkdir -p "$OUT_ROOT"
find "$PROTO_ROOT" -name '*.proto' -print0 | while IFS= read -r -d '' proto; do
  rel="${proto#"$PROTO_ROOT"/}"
  "$PY" -m grpc_tools.protoc \
    -I "$PROTO_ROOT" \
    --python_out="$OUT_ROOT" \
    --pyi_out="$OUT_ROOT" \
    --grpc_python_out="$OUT_ROOT" \
    "$rel"
  echo "generated $rel"
done

# protoc emits package directories without __init__.py; the bindings are an
# importable part of eidolon_sdk, not a loose namespace.
find "$OUT_ROOT" -type d -exec sh -c '[ -f "$1/__init__.py" ] || : > "$1/__init__.py"' _ {} \;
