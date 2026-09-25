import importlib.util
import json
from pathlib import Path


def test_session_vectors_are_produced_by_the_current_sdk():
    root = Path(__file__).resolve().parents[2] / "contracts/control/v1"
    spec = importlib.util.spec_from_file_location("session_goldens", root / "generate_session_goldens.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, expected in module.vectors().items():
        assert json.loads((root / "golden" / name).read_text()) == expected
