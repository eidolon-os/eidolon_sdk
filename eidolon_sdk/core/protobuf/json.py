"""JSON-safe Protocol Buffer conversion helpers.

This module owns wire-format conversion only. Projects keep their proto
message definitions and business handling in their own repositories.
"""

from __future__ import annotations

from typing import Any

from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct


def protobuf_struct_to_dict(struct: Struct | None) -> dict[str, Any]:
    """Convert a protobuf ``Struct`` into a recursively JSON-safe dict."""

    if struct is None:
        return {}
    return MessageToDict(struct, preserving_proto_field_name=True)
