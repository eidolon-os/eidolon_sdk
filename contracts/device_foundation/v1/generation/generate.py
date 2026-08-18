#!/usr/bin/env python3
"""Generate the reproducible Device Foundation V1 source catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _source_files(config: dict[str, object]) -> list[Path]:
    files: set[Path] = set()
    for pattern in config["source_globs"]:
        files.update(path for path in ROOT.glob(pattern) if path.is_file())
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


def build_catalog() -> dict[str, object]:
    config = json.loads((ROOT / "generation" / "config.json").read_text(encoding="utf-8"))
    entries: list[dict[str, object]] = []
    digest_input = bytearray()
    for path in _source_files(config):
        relative = path.relative_to(ROOT).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append({"path": relative, "sha256": digest, "size": path.stat().st_size})
        digest_input.extend(relative.encode("utf-8"))
        digest_input.extend(b"\0")
        digest_input.extend(digest.encode("ascii"))
        digest_input.extend(b"\n")
    return {
        "artifact": "eidolon-device-foundation-v1-canonical-source",
        "contract_version": "1.0",
        "generator": config["generator"],
        "generator_version": config["generator_version"],
        "source_digest": "sha256:" + hashlib.sha256(digest_input).hexdigest(),
        "files": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = ROOT / "generated" / "catalog.json"
    expected = _canonical_json(build_catalog())
    if args.check:
        if not output.exists() or output.read_bytes() != expected:
            print(f"generated artifact drift: {output}", file=sys.stderr)
            return 1
        print(f"generated artifact clean: {output}")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(expected)
    print(f"generated {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
