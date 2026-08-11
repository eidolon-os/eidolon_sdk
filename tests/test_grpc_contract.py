"""The published gRPC bindings must still match the contract they came from.

Committing generated code buys a release that ships exact Git commits, but it
costs the guarantee that the code matches the .proto. This test buys it back.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PROTO_ROOT = _ROOT / "contracts/grpc"
_BINDINGS = _ROOT / "eidolon_sdk/grpc"


def _generated(destination: Path) -> dict[str, bytes]:
    for proto in sorted(_PROTO_ROOT.rglob("*.proto")):
        subprocess.run(
            [
                sys.executable,
                "-m",
                "grpc_tools.protoc",
                "-I",
                str(_PROTO_ROOT),
                f"--python_out={destination}",
                f"--pyi_out={destination}",
                f"--grpc_python_out={destination}",
                str(proto.relative_to(_PROTO_ROOT)),
            ],
            cwd=_ROOT,
            check=True,
            capture_output=True,
        )
    # protoc writes to the path the bindings are imported from, so compare the
    # same subtree the repository publishes.
    published = destination / "eidolon_sdk/grpc"
    return {
        str(path.relative_to(published)): path.read_bytes()
        for path in sorted(published.rglob("*"))
        if path.is_file()
    }


def test_the_contract_plane_publishes_exactly_one_copy_of_each_proto() -> None:
    """A mirrored .proto drifts; the point of the Contract Plane is one copy."""

    protos = sorted(path.name for path in _PROTO_ROOT.rglob("*.proto"))
    assert protos == sorted(set(protos))
    assert protos, "the Contract Plane publishes no gRPC contract"


def test_committed_bindings_match_their_proto(tmp_path: Path) -> None:
    if shutil.which("python") is None and not sys.executable:
        pytest.skip("no interpreter available to run protoc")
    try:
        import grpc_tools  # noqa: F401
    except ImportError:  # pragma: no cover - only when dev extras are absent
        pytest.skip("grpcio-tools is not installed")

    expected = _generated(tmp_path)
    committed = {
        str(path.relative_to(_BINDINGS)): path.read_bytes()
        for path in sorted(_BINDINGS.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }
    # __init__.py files are ours, not protoc's.
    committed = {
        name: payload for name, payload in committed.items() if not name.endswith("__init__.py")
    }

    assert set(committed) == set(expected)
    stale = [name for name, payload in expected.items() if committed[name] != payload]
    assert not stale, (
        "committed gRPC bindings are stale; run ./scripts/gen_grpc_stubs.sh: " + ", ".join(stale)
    )
