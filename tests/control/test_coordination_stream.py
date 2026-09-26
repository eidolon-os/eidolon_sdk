import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.control.coordination_stream import CLIENT_FRAME, OpenScene, Transcript
from eidolon_sdk.biz.dialogue_control import CommittedTurnDecision, TurnCommitBoundary

from test_coordination import selection


def transcript(text="hello", boundary=TurnCommitBoundary.PTT_SEGMENT):
    return dict(
        type="transcript",
        capture_id="capture",
        text=text,
        commitment=CommittedTurnDecision.create(text=text, boundary=boundary).as_metadata(),
    )


def test_accepts_only_final_ptt_commit_bound_to_text():
    frame = transcript()
    assert CLIENT_FRAME.validate_python(frame).text == "hello"
    frame["text"] = "changed"
    with pytest.raises(ValidationError):
        CLIENT_FRAME.validate_python(frame)


def test_non_ptt_commit_and_missing_commit_are_refused():
    for boundary in TurnCommitBoundary:
        if boundary != TurnCommitBoundary.PTT_SEGMENT:
            with pytest.raises(ValidationError):
                Transcript.model_validate(transcript(boundary=boundary))
    frame = transcript()
    frame.pop("commitment")
    with pytest.raises(ValidationError):
        Transcript.model_validate(frame)


def test_empty_capture_cannot_claim_committed_user_speech():
    assert Transcript(type="transcript", capture_id="capture", text="").text == ""
    with pytest.raises(ValidationError):
        Transcript.model_validate(transcript(text=""))


@pytest.mark.parametrize("order", [("unknown",), ("companion-a", "companion-a"), ()])
def test_mock_policy_does_not_add_or_duplicate_members(order):
    with pytest.raises(ValidationError):
        OpenScene(type="open", owner_id="owner", selection=selection(), mock_order=order)


def test_explicit_mock_policy_and_group_scenario_round_trip():
    frame = OpenScene(
        type="open", owner_id="owner", selection=selection(), mock_order=("companion-b",)
    )
    assert OpenScene.model_validate_json(frame.model_dump_json()) == frame


@pytest.mark.parametrize(
    "frame",
    [
        dict(type="receipt", request_id="one", device_id="device", result="generated"),
        dict(type="press", capture_id="one", device_id="another-input"),
        dict(type="transcript", capture_id="one", text="x" * 32769),
        dict(type="open", owner_id="new-owner"),
    ],
)
def test_frames_cannot_change_scope_or_claim_model_done_as_played(frame):
    with pytest.raises(ValidationError):
        CLIENT_FRAME.validate_python(frame)


def test_server_reply_correlation_and_epoch_are_strict():
    from eidolon_sdk.biz.control.coordination_stream import SERVER_FRAME

    base = dict(
        type="reply_start",
        stream_id="stream",
        session_id="scene",
        request_id="turn",
        turn_id="turn",
        device_id="device",
        companion_id="a",
        epoch=1,
    )
    assert SERVER_FRAME.validate_python(base).epoch == 1
    for changes in (dict(epoch=True), dict(epoch=-1), dict(turn_id="other"), dict(extra="x")):
        with pytest.raises(ValueError):
            SERVER_FRAME.validate_python({**base, **changes})


def test_agent_preparation_cannot_claim_physical_readiness():
    from eidolon_sdk.biz.control.coordination_stream import SERVER_FRAME

    with pytest.raises(ValueError):
        SERVER_FRAME.validate_python(
            dict(
                type="prepared",
                stream_id="stream",
                session_id="scene",
                policy="explicit-demo-order-v1",
                physical_devices_ready=True,
            )
        )
