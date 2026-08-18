#!/usr/bin/env python3
"""Capture an immutable pre-slice HEAD manifest from the registered repository set."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


HERE = Path(__file__).resolve().parent


def _git(repo: Path, *args: str, allow_missing: bool = False) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=not allow_missing,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="strict").strip()


def _artifact_digest(repo: Path) -> str:
    tree = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "-z", "--full-tree", "HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    return "sha256:" + hashlib.sha256(tree).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, default=HERE / "cross-repo-heads.v1.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture-kind", required=True)
    parser.add_argument(
        "--head-only",
        action="store_true",
        help="capture committed HEADs and record clean pre-slice state",
    )
    args = parser.parse_args()
    document = json.loads(args.template.read_text(encoding="utf-8"))
    workspace = Path(document["workspace_root"])
    document["capture_kind"] = args.capture_kind
    document["captured_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    for entry in document["repositories"]:
        repo = workspace / entry["path"]
        entry["branch"] = _git(repo, "branch", "--show-current")
        entry["head_sha"] = _git(repo, "rev-parse", "HEAD")
        entry["remote"] = _git(repo, "remote", "get-url", "origin", allow_missing=True)
        entry["dirty"] = False if args.head_only else bool(
            _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        )
        entry.pop("dirty_note", None)
        entry["artifact_digest"] = _artifact_digest(repo)
    args.output.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
