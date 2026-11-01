"""Attribution contracts (design §3.5, decision 11)."""

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.speaker_identity import (
    IdentityDecisions,
    PersonEvidence,
    SpeakerEvidenceSource,
    SpeakerIdentityObservation,
    VoiceRef,
)
from eidolon_sdk.biz.voice_attribution import (
    MAX_VERDICT_REFS,
    VerdictEvidence,
    VoiceAttribution,
    VoiceVerdict,
    turn_verdict,
)
from eidolon_sdk.biz.voiceprint import ExtractedSample, SpeakerAudioQuality

MODEL = {"model_id": "m", "weights_hash": "a" * 64, "preprocessing_version": "v"}


def ref(turn="t1", session="s", channel="esp-box-3", owner="o", speech_ms=2400):
    return VoiceRef(owner_id=owner, session_id=session, turn_id=turn, speech_ms=speech_ms,
                    source=SpeakerEvidenceSource(request_id=turn, session_id=session, input_id="mic",
                                                 generation=1, sample_rate=16000, start_sample=0,
                                                 end_sample=48000, channel=channel))


def sample(**change):
    return ExtractedSample(**(MODEL | {"vector": [1.0, 0.0], "speech_ms": 2400} | change))


def verdict(**change):
    return VoiceVerdict(**({
        "kind": "attribute", "owner_id": "o", "refs": [ref("t1"), ref("t2")],
        "person_id": "p", "person_revision": 1,
        "evidence": VerdictEvidence(llr=6.0, posterior=0.998, posterior_unknown=0.001,
                                    condition="far_cross"),
        **MODEL, "backend_version": "b", "policy_version": "pv",
        "snapshot_revision": "c" * 64, "issued_at": 100.0, "expires_at": 105.0,
    } | change))


def someone_new():
    return VerdictEvidence(posterior_unknown=0.995, condition="far_cross")


def test_a_voice_reference_belongs_to_its_turn():
    assert ref().key() == ("o", "s", "t1")
    with pytest.raises(ValidationError, match="its turn"):
        VoiceRef(owner_id="o", session_id="s", turn_id="t2", speech_ms=100, source=ref("t1").source)
    with pytest.raises(ValidationError, match="its turn"):
        VoiceRef(owner_id="o", session_id="other", turn_id="t1", speech_ms=100, source=ref("t1").source)


def test_an_accumulated_verdict_names_the_person_with_same_voice_evidence():
    value = verdict()
    assert value.kind == "attribute" and len(value.refs) == 2
    with pytest.raises(ValidationError, match="only a discover"):
        verdict(person_id=None, person_revision=None)
    with pytest.raises(ValidationError, match="same-voice evidence"):
        verdict(evidence=someone_new())


def test_references_are_distinct_turns_of_one_owner():
    with pytest.raises(ValidationError, match="one reference per turn"):
        verdict(refs=[ref("t1"), ref("t1")])
    with pytest.raises(ValidationError, match="belong to the Owner"):
        verdict(refs=[ref("t1"), ref("t2", owner="x")])
    with pytest.raises(ValidationError):
        verdict(refs=[ref(f"t{i}") for i in range(MAX_VERDICT_REFS + 1)])
    with pytest.raises(ValidationError):
        verdict(refs=[])


def test_a_verdict_is_short_lived():
    for issued, expires in ((100, 100), (100, 99), (100, 111)):
        with pytest.raises(ValidationError, match="lifetime"):
            verdict(issued_at=issued, expires_at=expires)


def test_discovery_names_nobody_and_carries_the_new_template():
    value = verdict(kind="discover", person_id=None, person_revision=None, evidence=someone_new(),
                    sample=sample(), sample_channel="esp-box-3")
    assert value.person_id is None and value.sample is not None
    with pytest.raises(ValidationError, match="needs its template"):
        verdict(kind="discover", person_id=None, person_revision=None, evidence=someone_new())


def test_a_template_matches_the_model_and_a_channel_the_voice_was_heard_on():
    assert verdict(sample=sample(), sample_channel="esp-box-3").sample_channel == "esp-box-3"
    with pytest.raises(ValidationError, match="names its channel"):
        verdict(sample=sample())
    with pytest.raises(ValidationError, match="heard on"):
        verdict(sample=sample(), sample_channel="mobile")
    with pytest.raises(ValidationError, match="model"):
        verdict(sample=sample(model_id="other"), sample_channel="esp-box-3")


def test_only_attribute_and_merge_move_a_candidate():
    assert verdict(from_person_id="c").from_person_id == "c"
    assert verdict(kind="merge", from_person_id="c2").from_person_id == "c2"
    with pytest.raises(ValidationError, match="merged"):
        verdict(kind="merge")
    with pytest.raises(ValidationError, match="already is"):
        verdict(kind="merge", from_person_id="p")
    for kind in ("promote", "turn"):
        with pytest.raises(ValidationError, match="move a candidate"):
            verdict(kind=kind, refs=[ref()], from_person_id="c")


def test_merges_and_promotions_carry_no_template():
    assert verdict(kind="promote").sample is None
    with pytest.raises(ValidationError, match="no template"):
        verdict(kind="promote", sample=sample(), sample_channel="esp-box-3")


def test_a_turn_verdict_is_about_its_own_turn():
    with pytest.raises(ValidationError, match="its own turn"):
        verdict(kind="turn")


def observation(**change):
    return SpeakerIdentityObservation(**({
        "status": "compared", "reason": "compared", "owner_id": "o", "session_id": "s",
        "turn_id": "t1", "source": ref("t1", channel="mobile").source,
        **MODEL, "backend_version": "b", "policy_version": "pv",
        "evidence": [PersonEvidence(person_id="p", person_revision=3, maturity="established",
                                    is_named=True, profile_id="vp", profile_revision=1,
                                    llr=7.0, posterior=0.999)],
        "posterior_unknown": 0.0005, "condition": "near_same",
        "decisions": IdentityDecisions(personal_memory="p"),
        "audio_quality": SpeakerAudioQuality(audio_ms=3000, required_speech_ms=600, speech_ms=2100),
        "issued_at": 100.0, "expires_at": 105.0,
    } | change))


def test_the_turn_verdict_is_the_turns_personal_memory_decision():
    value = turn_verdict(observation(), snapshot_revision="c" * 64)
    assert (value.kind, value.person_id, value.person_revision) == ("turn", "p", 3)
    assert value.refs == [observation().voice_ref()] and value.refs[0].speech_ms == 2100
    assert (value.evidence.llr, value.evidence.condition) == (7.0, "near_same")
    assert (value.issued_at, value.expires_at) == (100.0, 105.0)
    with_template = turn_verdict(observation(), snapshot_revision="c" * 64, sample=sample())
    assert with_template.sample_channel == "mobile"


def test_no_turn_verdict_without_a_personal_memory_decision_or_audio():
    assert turn_verdict(observation(decisions=IdentityDecisions(addressing="p")),
                        snapshot_revision="c" * 64) is None
    assert turn_verdict(observation(audio_quality=None), snapshot_revision="c" * 64) is None


def attribution(**change):
    return VoiceAttribution(**({
        "attribution_id": "a1", "revision": 1, "owner_id": "o", "person_id": "p",
        "person_revision": 2, "refs": [ref("t1"), ref("t2")], "source": "accumulated",
        "recorded_at": 200.0,
    } | change))


def test_an_attribution_records_its_source_and_can_be_revoked():
    value = attribution()
    assert (value.source, value.revoked) == ("accumulated", False)
    assert attribution(source="owner", revision=2, revoked=True).revoked
    with pytest.raises(ValidationError):
        attribution(source="guess")
    with pytest.raises(ValidationError, match="one reference per turn"):
        attribution(refs=[ref("t1"), ref("t1")])
