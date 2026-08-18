#!/usr/bin/env python3
"""Generate and verify Device Foundation V1 canonical artifacts and bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EIDOLON_ROOT = ROOT.parents[3]


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _source_files(config: dict[str, object]) -> list[Path]:
    files: set[Path] = set()
    for pattern in config["source_globs"]:
        files.update(path for path in ROOT.glob(pattern) if path.is_file())
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


def _load_config() -> dict[str, object]:
    return json.loads((ROOT / "generation" / "config.json").read_text(encoding="utf-8"))


def build_catalog(config: dict[str, object]) -> dict[str, object]:
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


def build_outputs(config: dict[str, object]) -> dict[Path, bytes]:
    outputs = {
        ROOT / "generated" / "catalog.json": _canonical_json(build_catalog(config)),
    }
    for binding in config["binding_outputs"]:
        template = ROOT / binding["template"]
        output = EIDOLON_ROOT / binding["repo"] / binding["path"]
        outputs[output] = template.read_bytes()
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    config = _load_config()
    outputs = build_outputs(config)
    if args.check:
        drift = [path for path, expected in outputs.items() if not path.exists() or path.read_bytes() != expected]
        if drift:
            for path in drift:
                print(f"generated artifact drift: {path}", file=sys.stderr)
            return 1
        for path in outputs:
            print(f"generated artifact clean: {path}")
        return 0
    for output, expected in outputs.items():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(expected)
        print(f"generated {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
