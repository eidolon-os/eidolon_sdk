from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from eidolon_sdk.biz.speech_voice import (
    CatalogVoiceSelection,
    CompanionSpeechVoice,
    HostVoiceCatalog,
    OwnerVoice,
    OwnerVoiceBinding,
    OwnerVoiceKey,
    OwnerVoiceSelection,
    SpeechVoiceRecord,
    SpeechVoiceSelection,
    VoiceOption,
    VoiceRef,
    catalog_voice_key,
    decode_voice_key,
    owner_voice_key,
    style_labels,
)
from eidolon_sdk.biz.system_data import SystemDataContractError, SystemDataRuntimeClient

NOW = datetime(2026, 10, 31, tzinfo=UTC)


def test_catalog_voice_key_is_url_safe_and_reversible() -> None:
    ref = VoiceRef(provider="bailian", model="qwen-audio-3.1-tts-flash", voice_id="longanyang_v3.1")
    key = catalog_voice_key(ref)
    assert all(c.isalnum() or c in "-_." for c in key)
    assert decode_voice_key(key) == ref


def test_owner_voice_key_round_trips_and_garbage_is_rejected() -> None:
    assert decode_voice_key(owner_voice_key("ov_1")) == OwnerVoiceKey(voice_asset_id="ov_1")
    for bad in ("", "x.abc", "c.!!!", "c." + "e30"):
        with pytest.raises(ValueError):
            decode_voice_key(bad)


def test_selection_is_discriminated_by_source() -> None:
    adapter = TypeAdapter(SpeechVoiceSelection)
    catalog = adapter.validate_python(
        {"source": "catalog", "provider": "bailian", "model": "m", "voice_id": "v", "display_name": "龙安欢"}
    )
    owner = adapter.validate_python({"source": "owner_voice", "voice_asset_id": "ov_1", "display_name": "小禾"})
    assert isinstance(catalog, CatalogVoiceSelection) and catalog.ref.voice_id == "v"
    assert isinstance(owner, OwnerVoiceSelection)
    with pytest.raises(ValidationError):
        adapter.validate_python({"source": "cloned", "voice_asset_id": "x", "display_name": "x"})


def test_absent_record_means_follow_the_host() -> None:
    assert SpeechVoiceRecord(revision=0).selection is None


def test_unknown_vocabulary_travels_but_is_not_labelled() -> None:
    option = VoiceOption(
        voice_key="k", ref=VoiceRef(provider="p", model="m", voice_id="v"), display_name="x",
        gender="nonbinary-future", age_band="youth", languages=["zh-CN"], styles=["warm", "new-style"],
        style_labels=style_labels(["warm", "new-style"]), rank=1,
    )
    assert option.style_labels == ["温暖"]
    catalog = HostVoiceCatalog(catalog_revision="r", state="fresh", host_selectable=True, voices=[option])
    assert catalog.option("k") is option and catalog.option("other") is None


def test_owner_voice_finds_the_binding_for_a_model() -> None:
    binding = OwnerVoiceBinding(provider="bailian", model="m1", provider_voice_id="m1-e1-x", status="ready")
    voice = OwnerVoice(
        voice_asset_id="ov_1", owner_id="o", name="小禾", method="design", state="active", revision=1,
        operation_id="op-design-1",
        bindings=[binding], created_at=NOW, updated_at=NOW,
    )
    assert voice.binding_for("bailian", "m1") is binding
    assert voice.binding_for("bailian", "m2") is None


@pytest.mark.asyncio
async def test_runtime_client_reads_a_companion_speech_voice() -> None:
    body = CompanionSpeechVoice(
        companion_id="companion/a", revision=2,
        selection=OwnerVoiceSelection(voice_asset_id="ov_1", display_name="小禾", selected_at=NOW),
    ).model_dump(mode="json")

    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path)
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SystemDataRuntimeClient(http, "http://data.local", service_token="service-token-with-at-least-24-chars")
        result = await client.get_companion_speech_voice("companion/a")
        assert seen[0].endswith(b"/companions/companion%2Fa/speech-voice")
        assert result.revision == 2 and isinstance(result.selection, OwnerVoiceSelection)
        with pytest.raises(SystemDataContractError):
            await client.get_companion_speech_voice("someone-else")
