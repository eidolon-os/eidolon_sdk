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
    imports = _imports_under("biz/registry")
    forbidden = ("eidolon_sdk.core.db", "eidolon_sdk.core.kv", "eidolon_sdk.adapters")
    assert not any(imp.startswith(forbidden) for imp in imports)


def test_db_layer_does_not_import_registry_domain() -> None:
    imports = _imports_under("core/db")
    assert not any(imp.startswith("eidolon_sdk.biz.registry") for imp in imports)


def test_http_layer_does_not_import_domain_or_storage_layers() -> None:
    imports = _imports_under("core/http")
    forbidden = (
        "eidolon_sdk.adapters",
        "eidolon_sdk.core.db",
        "eidolon_sdk.core.kv",
        "eidolon_sdk.biz.registry",
        "eidolon_sdk.biz.runtime",
    )
    assert not any(imp.startswith(forbidden) for imp in imports)


def test_wire_contract_layers_do_not_import_storage_or_service_clients() -> None:
    forbidden = (
        "eidolon_sdk.adapters",
        "eidolon_sdk.biz.admin",
        "eidolon_sdk.core.db",
        "eidolon_sdk.core.http",
        "eidolon_sdk.core.kv",
    )
    for package in (
        "integrations/llm",
        "biz/long_tasks",
        "core/protobuf",
        "core/streaming",
    ):
        imports = _imports_under(package)
        assert not any(imp.startswith(forbidden) for imp in imports)


def test_core_layer_does_not_import_business_or_adapters() -> None:
    imports = _imports_under("core")
    forbidden = (
        "eidolon_sdk.adapters",
        "eidolon_sdk.biz",
        "eidolon_sdk.memory",
    )
    assert not any(imp.startswith(forbidden) for imp in imports)


def test_business_layer_does_not_import_adapters() -> None:
    imports = _imports_under("biz")
    assert not any(imp.startswith("eidolon_sdk.adapters") for imp in imports)
