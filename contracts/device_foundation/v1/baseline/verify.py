#!/usr/bin/env python3
"""Fail closed when the cross-repo project set or captured Git facts drift."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "cross-repo-heads.v1.json"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.decode("utf-8", errors="strict").strip()


def _discover(workspace: Path) -> set[str]:
    projects: set[str] = set()
    for marker in workspace.rglob(".git"):
        if not marker.is_dir():
            continue
        relative = marker.parent.relative_to(workspace)
        if any(part in {".worktrees", ".claude", ".migration-backups"} for part in relative.parts):
            continue
        projects.add(relative.as_posix())
    return projects


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
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument(
        "--exact", action="store_true", help="also compare captured branch/HEAD/dirty/digest"
    )
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    workspace = (args.workspace_root or Path(manifest["workspace_root"])).resolve()
    expected_entries = {entry["path"]: entry for entry in manifest["repositories"]}
    expected = set(expected_entries)
    actual = _discover(workspace)
    if actual != expected:
        print(
            json.dumps(
                {
                    "ok": False,
                    "added_repositories": sorted(actual - expected),
                    "missing_repositories": sorted(expected - actual),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    non_main_participants = [
        path
        for path, entry in expected_entries.items()
        if entry["participation"] != "out-of-scope" and entry["branch"] != "main"
    ]
    if non_main_participants:
        print(
            f"participating repositories are not based on main: {non_main_participants}",
            file=sys.stderr,
        )
        return 1
    if args.exact:
        drift: dict[str, dict[str, object]] = {}
        for path, entry in expected_entries.items():
            repo = workspace / path
            actual_entry = {
                "branch": _git(repo, "branch", "--show-current"),
                "head_sha": _git(repo, "rev-parse", "HEAD"),
                "dirty": bool(_git(repo, "status", "--porcelain=v1", "--untracked-files=all")),
                "artifact_digest": _artifact_digest(repo),
            }
            expected_entry = {key: entry[key] for key in actual_entry}
            if actual_entry != expected_entry:
                drift[path] = {"expected": expected_entry, "actual": actual_entry}
        if drift:
            print(
                json.dumps({"ok": False, "drift": drift}, indent=2, sort_keys=True), file=sys.stderr
            )
            return 1
    print(
        json.dumps(
            {"ok": True, "repository_count": len(actual), "exact": args.exact}, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
