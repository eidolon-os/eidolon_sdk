from __future__ import annotations

import ast
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "eidolon_sdk"


def _imports_under(package: str) -> set[str]:
    root = PACKAGE_ROOT / package
    imports: set[str] = set()
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


def test_registry_layer_is_storage_agnostic() -> None:
    imports = _imports_under("registry")
    forbidden = ("eidolon_sdk.db", "eidolon_sdk.kv", "eidolon_sdk.adapters")
    assert not any(imp.startswith(forbidden) for imp in imports)


def test_db_layer_does_not_import_registry_domain() -> None:
    imports = _imports_under("db")
    assert not any(imp.startswith("eidolon_sdk.registry") for imp in imports)

