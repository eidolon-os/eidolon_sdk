from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ChatRequest(_message.Message):
    __slots__ = ("start", "cancel", "signal", "presentation_feedback", "motion_feedback", "channel_tool_result")
    START_FIELD_NUMBER: _ClassVar[int]
    CANCEL_FIELD_NUMBER: _ClassVar[int]
    SIGNAL_FIELD_NUMBER: _ClassVar[int]
    PRESENTATION_FEEDBACK_FIELD_NUMBER: _ClassVar[int]
    MOTION_FEEDBACK_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_TOOL_RESULT_FIELD_NUMBER: _ClassVar[int]
    start: StartTurn
    cancel: CancelTurn
    signal: PushSignalInline
    presentation_feedback: PresentationFeedback
    motion_feedback: MotionFeedback
    channel_tool_result: ChannelToolResult
    def __init__(self, start: _Optional[_Union[StartTurn, _Mapping]] = ..., cancel: _Optional[_Union[CancelTurn, _Mapping]] = ..., signal: _Optional[_Union[PushSignalInline, _Mapping]] = ..., presentation_feedback: _Optional[_Union[PresentationFeedback, _Mapping]] = ..., motion_feedback: _Optional[_Union[MotionFeedback, _Mapping]] = ..., channel_tool_result: _Optional[_Union[ChannelToolResult, _Mapping]] = ...) -> None: ...

class StartTurn(_message.Message):
    __slots__ = ("turn_id", "conversation_id", "text", "realtime", "metadata", "trace_id", "speculative", "input_modality", "channel_tool_capabilities")
    TURN_ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    REALTIME_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    SPECULATIVE_FIELD_NUMBER: _ClassVar[int]
    INPUT_MODALITY_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_TOOL_CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    turn_id: str
    conversation_id: str
    text: str
    realtime: _struct_pb2.Struct
    metadata: _struct_pb2.Struct
    trace_id: str
    speculative: bool
    input_modality: str
    channel_tool_capabilities: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, turn_id: _Optional[str] = ..., conversation_id: _Optional[str] = ..., text: _Optional[str] = ..., realtime: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., metadata: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., trace_id: _Optional[str] = ..., speculative: bool = ..., input_modality: _Optional[str] = ..., channel_tool_capabilities: _Optional[_Iterable[str]] = ...) -> None: ...

class CancelTurn(_message.Message):
    __slots__ = ("turn_id", "played_chars", "played_ms")
    TURN_ID_FIELD_NUMBER: _ClassVar[int]
    PLAYED_CHARS_FIELD_NUMBER: _ClassVar[int]
    PLAYED_MS_FIELD_NUMBER: _ClassVar[int]
    turn_id: str
    played_chars: int
    played_ms: float
    def __init__(self, turn_id: _Optional[str] = ..., played_chars: _Optional[int] = ..., played_ms: _Optional[float] = ...) -> None: ...

class PushSignalInline(_message.Message):
    __slots__ = ("modality", "label", "confidence", "raw", "ts")
    MODALITY_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    RAW_FIELD_NUMBER: _ClassVar[int]
    TS_FIELD_NUMBER: _ClassVar[int]
    modality: str
    label: str
    confidence: float
    raw: _struct_pb2.Struct
    ts: _timestamp_pb2.Timestamp
    def __init__(self, modality: _Optional[str] = ..., label: _Optional[str] = ..., confidence: _Optional[float] = ..., raw: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., ts: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class TurnEvent(_message.Message):
    __slots__ = ("turn_id", "seq", "kind", "data", "ts", "presentation", "motion", "channel_tool_call", "channel_tool_cancel")
    class Kind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        KIND_UNSPECIFIED: _ClassVar[TurnEvent.Kind]
        STATE: _ClassVar[TurnEvent.Kind]
        DELTA: _ClassVar[TurnEvent.Kind]
        TOOL_CALL: _ClassVar[TurnEvent.Kind]
        TOOL_RESULT: _ClassVar[TurnEvent.Kind]
        CITATION: _ClassVar[TurnEvent.Kind]
        USAGE: _ClassVar[TurnEvent.Kind]
        DONE: _ClassVar[TurnEvent.Kind]
        ERROR: _ClassVar[TurnEvent.Kind]
        ACK: _ClassVar[TurnEvent.Kind]
        PROGRESS: _ClassVar[TurnEvent.Kind]
        HANDOFF: _ClassVar[TurnEvent.Kind]
        PRESENTATION: _ClassVar[TurnEvent.Kind]
        MOTION: _ClassVar[TurnEvent.Kind]
        CHANNEL_TOOL_CALL: _ClassVar[TurnEvent.Kind]
        CHANNEL_TOOL_CANCEL: _ClassVar[TurnEvent.Kind]
    KIND_UNSPECIFIED: TurnEvent.Kind
    STATE: TurnEvent.Kind
    DELTA: TurnEvent.Kind
    TOOL_CALL: TurnEvent.Kind
    TOOL_RESULT: TurnEvent.Kind
    CITATION: TurnEvent.Kind
    USAGE: TurnEvent.Kind
    DONE: TurnEvent.Kind
    ERROR: TurnEvent.Kind
    ACK: TurnEvent.Kind
    PROGRESS: TurnEvent.Kind
    HANDOFF: TurnEvent.Kind
    PRESENTATION: TurnEvent.Kind
    MOTION: TurnEvent.Kind
    CHANNEL_TOOL_CALL: TurnEvent.Kind
    CHANNEL_TOOL_CANCEL: TurnEvent.Kind
    TURN_ID_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    TS_FIELD_NUMBER: _ClassVar[int]
    PRESENTATION_FIELD_NUMBER: _ClassVar[int]
    MOTION_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_TOOL_CALL_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_TOOL_CANCEL_FIELD_NUMBER: _ClassVar[int]
    turn_id: str
    seq: int
    kind: TurnEvent.Kind
    data: _struct_pb2.Struct
    ts: float
    presentation: ResponseIntent
    motion: HeadMotionRequest
    channel_tool_call: ChannelToolCall
    channel_tool_cancel: ChannelToolCancel
    def __init__(self, turn_id: _Optional[str] = ..., seq: _Optional[int] = ..., kind: _Optional[_Union[TurnEvent.Kind, str]] = ..., data: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., ts: _Optional[float] = ..., presentation: _Optional[_Union[ResponseIntent, _Mapping]] = ..., motion: _Optional[_Union[HeadMotionRequest, _Mapping]] = ..., channel_tool_call: _Optional[_Union[ChannelToolCall, _Mapping]] = ..., channel_tool_cancel: _Optional[_Union[ChannelToolCancel, _Mapping]] = ...) -> None: ...

class ChannelToolCall(_message.Message):
    __slots__ = ("call_id", "name", "arguments")
    CALL_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    ARGUMENTS_FIELD_NUMBER: _ClassVar[int]
    call_id: str
    name: str
    arguments: _struct_pb2.Struct
    def __init__(self, call_id: _Optional[str] = ..., name: _Optional[str] = ..., arguments: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class ChannelToolResult(_message.Message):
    __slots__ = ("turn_id", "call_id", "name", "ok", "content", "error_code", "error_message", "outcome_state", "reference_context")
    TURN_ID_FIELD_NUMBER: _ClassVar[int]
    CALL_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    OK_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_STATE_FIELD_NUMBER: _ClassVar[int]
    REFERENCE_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    turn_id: str
    call_id: str
    name: str
    ok: bool
    content: _struct_pb2.Struct
    error_code: str
    error_message: str
    outcome_state: str
    reference_context: _struct_pb2.Struct
    def __init__(self, turn_id: _Optional[str] = ..., call_id: _Optional[str] = ..., name: _Optional[str] = ..., ok: bool = ..., content: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., error_code: _Optional[str] = ..., error_message: _Optional[str] = ..., outcome_state: _Optional[str] = ..., reference_context: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class ChannelToolCancel(_message.Message):
    __slots__ = ("turn_id", "call_id")
    TURN_ID_FIELD_NUMBER: _ClassVar[int]
    CALL_ID_FIELD_NUMBER: _ClassVar[int]
    turn_id: str
    call_id: str
    def __init__(self, turn_id: _Optional[str] = ..., call_id: _Optional[str] = ...) -> None: ...

class HeadMotionRequest(_message.Message):
    __slots__ = ("command_id", "action", "times")
    COMMAND_ID_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    TIMES_FIELD_NUMBER: _ClassVar[int]
    command_id: str
    action: str
    times: int
    def __init__(self, command_id: _Optional[str] = ..., action: _Optional[str] = ..., times: _Optional[int] = ...) -> None: ...

class ResponseIntent(_message.Message):
    __slots__ = ("schema_version", "response_id", "turn_id", "session_id", "intent", "stance", "intensity", "pace", "outcome_ref")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_ID_FIELD_NUMBER: _ClassVar[int]
    TURN_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    INTENT_FIELD_NUMBER: _ClassVar[int]
    STANCE_FIELD_NUMBER: _ClassVar[int]
    INTENSITY_FIELD_NUMBER: _ClassVar[int]
    PACE_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_REF_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    response_id: str
    turn_id: str
    session_id: str
    intent: str
    stance: str
    intensity: float
    pace: str
    outcome_ref: str
    def __init__(self, schema_version: _Optional[int] = ..., response_id: _Optional[str] = ..., turn_id: _Optional[str] = ..., session_id: _Optional[str] = ..., intent: _Optional[str] = ..., stance: _Optional[str] = ..., intensity: _Optional[float] = ..., pace: _Optional[str] = ..., outcome_ref: _Optional[str] = ...) -> None: ...

class MotionFeedback(_message.Message):
    __slots__ = ("turn_id", "receipt")
    TURN_ID_FIELD_NUMBER: _ClassVar[int]
    RECEIPT_FIELD_NUMBER: _ClassVar[int]
    turn_id: str
    receipt: _struct_pb2.Struct
    def __init__(self, turn_id: _Optional[str] = ..., receipt: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class PresentationFeedback(_message.Message):
    __slots__ = ("turn_id", "receipt")
    TURN_ID_FIELD_NUMBER: _ClassVar[int]
    RECEIPT_FIELD_NUMBER: _ClassVar[int]
    turn_id: str
    receipt: PresentationReceipt
    def __init__(self, turn_id: _Optional[str] = ..., receipt: _Optional[_Union[PresentationReceipt, _Mapping]] = ...) -> None: ...

class PresentationReceipt(_message.Message):
    __slots__ = ("schema_version", "presentation_id", "response_id", "status", "sequence", "reason", "elapsed_ms")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    PRESENTATION_ID_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    ELAPSED_MS_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    presentation_id: str
    response_id: str
    status: str
    sequence: int
    reason: str
    elapsed_ms: int
    def __init__(self, schema_version: _Optional[int] = ..., presentation_id: _Optional[str] = ..., response_id: _Optional[str] = ..., status: _Optional[str] = ..., sequence: _Optional[int] = ..., reason: _Optional[str] = ..., elapsed_ms: _Optional[int] = ...) -> None: ...

class SignalRequest(_message.Message):
    __slots__ = ("signal",)
    SIGNAL_FIELD_NUMBER: _ClassVar[int]
    signal: PushSignalInline
    def __init__(self, signal: _Optional[_Union[PushSignalInline, _Mapping]] = ...) -> None: ...

class Ack(_message.Message):
    __slots__ = ("accepted", "note")
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    NOTE_FIELD_NUMBER: _ClassVar[int]
    accepted: bool
    note: str
    def __init__(self, accepted: bool = ..., note: _Optional[str] = ...) -> None: ...

class SubscribeRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ProactiveEvent(_message.Message):
    __slots__ = ("instance_id", "intent", "text", "style_hint", "ts")
    INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    INTENT_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    STYLE_HINT_FIELD_NUMBER: _ClassVar[int]
    TS_FIELD_NUMBER: _ClassVar[int]
    instance_id: str
    intent: str
    text: str
    style_hint: str
    ts: _timestamp_pb2.Timestamp
    def __init__(self, instance_id: _Optional[str] = ..., intent: _Optional[str] = ..., text: _Optional[str] = ..., style_hint: _Optional[str] = ..., ts: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
