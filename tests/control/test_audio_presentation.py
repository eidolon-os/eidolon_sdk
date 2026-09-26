import pytest
from eidolon_sdk.biz.control.audio_presentation import AudioPresentation, AudioPresentationResult


def request():
    return AudioPresentation(session_id="scene", turn_id="turn", stream_id="stream", epoch=1)


def test_confirmation_requires_complete_matching_presentation():
    data = dict(
        session_id="scene",
        turn_id="turn",
        stream_id="stream",
        epoch=1,
        rendered_bytes=640,
        drained=True,
    )
    assert AudioPresentationResult(**data).confirms(request(), 640)
    for field, wrong in (
        ("session_id", "old"),
        ("turn_id", "old"),
        ("stream_id", "old"),
        ("epoch", 2),
        ("rendered_bytes", 320),
    ):
        assert not AudioPresentationResult(**{**data, field: wrong}).confirms(request(), 640)
    assert not AudioPresentationResult(**{**data, "rendered_bytes": 0}).confirms(request(), 0)


@pytest.mark.parametrize(
    "change",
    [
        dict(epoch=True),
        dict(sample_rate=24000),
        dict(channels=2),
        dict(format="opus"),
        dict(extra=True),
    ],
)
def test_unagreed_media_format_is_rejected(change):
    with pytest.raises(ValueError):
        AudioPresentation.model_validate({**request().model_dump(), **change})
