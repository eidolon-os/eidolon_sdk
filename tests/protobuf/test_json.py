from __future__ import annotations

from google.protobuf.struct_pb2 import Struct

from eidolon_sdk.core.protobuf import protobuf_struct_to_dict


def test_protobuf_struct_to_dict_is_recursive_json_safe() -> None:
    payload = Struct()
    payload.update(
        {
            "name": "get_time",
            "content": {
                "now": "2026-06-16 13:40:20 CST",
                "values": [1, True, None],
            },
        }
    )

    out = protobuf_struct_to_dict(payload)

    assert out == {
        "name": "get_time",
        "content": {
            "now": "2026-06-16 13:40:20 CST",
            "values": [1, True, None],
        },
    }


def test_protobuf_struct_to_dict_handles_none() -> None:
    assert protobuf_struct_to_dict(None) == {}
