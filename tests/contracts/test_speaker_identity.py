import time

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.speaker_identity import (
    IdentityDecisions,
    IdentityPolicy,
    PersonEvidence,
    SpeakerEvidenceSource,
    SpeakerIdentityObservation,
    UseThresholds,
    channel_class,
    comparison_condition,
)


def source(**change):
    return SpeakerEvidenceSource(**({"request_id": "r", "input_id": "mic", "generation": 1,
        "sample_rate": 16000, "start_sample": 0, "end_sample": 16000, "channel": "mobile"} | change))


def evidence(person="p", posterior=0.97, maturity="established", llr=4.0):
    return PersonEvidence(person_id=person, person_revision=1, maturity=maturity, is_named=True,
                          profile_id="v" + person, profile_revision=1, llr=llr, posterior=posterior)


def compared(**change):
    return SpeakerIdentityObservation(**({
        "status": "compared", "reason": "compared", "owner_id": "o", "source": source(),
        "model_id": "m", "weights_hash": "a" * 64, "preprocessing_version": "v",
        "backend_version": "b", "policy_version": "p", "evidence": [evidence()],
        "posterior_unknown": 0.03, "condition": "near_same",
    } | change))


def test_evidence_without_comparison_carries_no_posterior_or_decision():
    value = SpeakerIdentityObservation(status="uncertain", owner_id="o", reason="speech_too_short")
    assert value.evidence == [] and value.decisions == IdentityDecisions()
    for change in ({"evidence": [evidence()]}, {"posterior_unknown": 0.5},
                   {"decisions": IdentityDecisions(discovery=True)}, {"condition": "near_same"}):
        with pytest.raises(ValidationError):
            SpeakerIdentityObservation(status="unavailable", owner_id="o", reason="timeout", **change)


def test_compared_evidence_requires_audio_versions_and_posteriors():
    assert compared().decided("personal_memory") is None
    for change in ({"source": None}, {"backend_version": None}, {"policy_version": None},
                   {"posterior_unknown": None}, {"weights_hash": None}):
        with pytest.raises(ValidationError):
            compared(**change)


def test_posteriors_are_a_distribution():
    with pytest.raises(ValidationError, match="exceed one"):
        compared(evidence=[evidence("a", 0.6), evidence("b", 0.5)], posterior_unknown=0.0)
    with pytest.raises(ValidationError, match="one evidence entry"):
        compared(evidence=[evidence("a", 0.4), evidence("a", 0.4)])


def test_each_use_names_a_compared_person_or_nobody():
    value = compared(decisions=IdentityDecisions(personal_memory="p", addressing="p", speaker_label="p"),
                     display_name="劲松")
    assert value.decided("personal_memory").person_id == "p"
    assert value.decided("candidate_evidence") is None
    with pytest.raises(ValidationError, match="compared Person"):
        compared(decisions=IdentityDecisions(speaker_label="someone-else"))


def test_someone_new_is_never_also_a_known_person():
    assert compared(evidence=[evidence(posterior=0.001)], posterior_unknown=0.999,
                    decisions=IdentityDecisions(discovery=True)).decisions.discovery
    with pytest.raises(ValidationError, match="someone new"):
        compared(decisions=IdentityDecisions(discovery=True, addressing="p"))


def test_candidate_evidence_names_only_a_candidate():
    candidate = compared(evidence=[evidence(maturity="candidate")],
                         decisions=IdentityDecisions(candidate_evidence="p"))
    assert candidate.decided("candidate_evidence").maturity == "candidate"
    with pytest.raises(ValidationError, match="name a candidate"):
        compared(decisions=IdentityDecisions(candidate_evidence="p"))


def test_personal_details_accompany_only_an_addressing_decision():
    with pytest.raises(ValidationError, match="addressing"):
        compared(display_name="劲松")
    with pytest.raises(ValidationError, match="addressing"):
        compared(decisions=IdentityDecisions(personal_memory="p"), display_name="劲松")


def test_a_source_names_its_capture_channel():
    with pytest.raises(ValidationError):
        SpeakerEvidenceSource(request_id="r", input_id="mic", generation=1, sample_rate=16000,
                              start_sample=0, end_sample=16000)
    with pytest.raises(ValidationError):
        source(end_sample=0)


@pytest.mark.parametrize("kind,expected", [
    ("eidolon-mobile-android", "mobile"), ("eidolon-mobile-ios", "mobile"),
    ("esp32-s3-box3", "esp32-s3-box3"), (None, "unknown"), ("", "unknown"),
])
def test_every_phone_app_is_one_channel(kind, expected):
    assert channel_class(kind) == expected


@pytest.mark.parametrize("template,probe,expected", [
    ("mobile", "mobile", "near_same"),
    ("esp-box-3", "esp-box-3", "far_same"),
    ("mobile", "esp-box-3", "far_cross"),
    ("esp-box-3", "mobile", "far_cross"),
    ("esp-box-3", "m5stack-stackchan", "far_cross"),
    ("unknown", "unknown", "far_cross"),
])
def test_the_condition_follows_the_template_and_probe_channels(template, probe, expected):
    assert comparison_condition(template, probe) == expected


def uses(**change):
    return {"personal_memory": 0.99, "addressing": 0.9, "speaker_label": 0.9,
            "candidate_evidence": 0.95, "discovery": 0.99} | change


def policy(conditions=None, **change):
    return IdentityPolicy(**({
        "version": "p", "model_id": "m", "weights_hash": "a" * 64, "preprocessing_version": "v",
        "backend_version": "b", "min_speech_ms": 600, "min_unknown_speech_ms": 1500,
        "prior_unknown": 0.5, "household_margin_llr": 1.0, "track_continuation_llr": 3.0,
        "conditions": conditions or {c: uses() for c in ("near_same", "far_same", "far_cross")},
    } | change))


def test_identity_policy_bounds():
    assert policy().thresholds("far_cross").personal_memory == 0.99
    for change in ({"min_unknown_speech_ms": 500}, {"prior_unknown": 0}, {"prior_unknown": 1},
                   {"household_margin_llr": -1}, {"track_continuation_llr": -0.1},
                   {"track_continuation_llr": float("nan")}):
        with pytest.raises(ValidationError):
            policy(**change)
    for change in ({"personal_memory": 0.4}, {"discovery": 1.0}):
        with pytest.raises(ValidationError):
            UseThresholds(**uses(**change))


def test_every_condition_has_its_own_thresholds():
    value = policy({"near_same": uses(), "far_same": uses(personal_memory=None),
                    "far_cross": uses(personal_memory=None, addressing=0.95)})
    assert value.thresholds("near_same").personal_memory == 0.99
    assert value.thresholds("far_same").personal_memory is None
    assert value.thresholds("far_cross").addressing == 0.95
    with pytest.raises(ValidationError, match="every comparison condition"):
        policy({"near_same": uses(), "far_same": uses()})
    with pytest.raises(ValidationError):
        policy({"near_same": uses(), "far_same": uses(), "far_cross": uses(), "elsewhere": uses()})


def test_a_compared_observation_names_its_condition():
    assert compared().condition == "near_same"
    with pytest.raises(ValidationError):
        compared(condition="cross")


@pytest.mark.parametrize("change", [
    {"subject_role": "visible_person"}, {"modalities": ["face"]},
    {"modalities": ["voice", "face"]}, {"modalities": []},
])
def test_unresolved_internal_contract_cannot_assert_visual_identity(change):
    with pytest.raises(ValidationError):
        SpeakerIdentityObservation(status="uncertain", owner_id="o", reason="pending", **change)


def test_internal_observation_rejects_mismatched_evidence_session():
    with pytest.raises(ValidationError, match="evidence session"):
        SpeakerIdentityObservation(status="uncertain", owner_id="o", session_id="other",
            source=source(session_id="original"), reason="pending")


@pytest.mark.parametrize("change", [{"issued_at": float("inf")}, {"expires_at": float("nan")}])
def test_nonfinite_observation_times_are_invalid(change):
    with pytest.raises(ValidationError):
        SpeakerIdentityObservation(status="unavailable", owner_id="o", reason="timeout", **change)


def test_observation_attestation_roundtrips_and_cannot_renew_expired_evidence():
    from eidolon_sdk.biz.speaker_attestation import sign_observation, verify_observation
    now = time.time()
    value = compared(session_id="s", turn_id="t", source=source(session_id="s", request_id="t"),
                     issued_at=now, expires_at=now + 10,
                     decisions=IdentityDecisions(personal_memory="p", addressing="p"), display_name="劲松")
    token = sign_observation(value, secret="x" * 32, text="hello")
    assert verify_observation(token, secret="x" * 32, owner_id="o", session_id="s", turn_id="t",
                              text="hello") == value
    stale = value.model_copy(update={"issued_at": now - 20, "expires_at": now - 10})
    with pytest.raises(ValueError):
        sign_observation(stale, secret="x" * 32, text="hello")


def test_voiceprint_profiles_require_a_person_from_creation():
    from eidolon_sdk.biz.voiceprint import SpeakerProfileView

    fields = dict(profile_id="v", display_name="Alice", revision=1, enrollment_id="e")
    assert SpeakerProfileView(person_id="p", **fields).person_id == "p"
    for invalid in ({}, {"person_id": None}, {"person_id": ""}):
        with pytest.raises(ValidationError):
            SpeakerProfileView(**fields, **invalid)


def test_observation_profile_provenance_never_fabricates_an_enrollment():
    from eidolon_sdk.biz.voiceprint import SpeakerProfileView
    fields = dict(person_id="p", profile_id="v", display_name="匿名", revision=1)
    result = SpeakerProfileView(**fields, origin="observation", source_observation_id="observation")
    assert result.enrollment_id is None
    for provenance in [dict(origin="observation"),
                       dict(origin="observation", enrollment_id="fake", source_observation_id="o"),
                       dict(origin="enrollment", enrollment_id="e", source_observation_id="o")]:
        with pytest.raises(ValidationError):
            SpeakerProfileView(**fields, **provenance)


def test_a_use_without_a_threshold_is_switched_off():
    assert UseThresholds(**uses(personal_memory=None, discovery=None)).personal_memory is None
    with pytest.raises(ValidationError):
        UseThresholds(**{k: v for k, v in uses().items() if k != "addressing"})


def test_every_turn_with_measured_audio_names_its_voice():
    from eidolon_sdk.biz.voiceprint import SpeakerAudioQuality

    heard = SpeakerAudioQuality(audio_ms=2000, required_speech_ms=600, speech_ms=450)
    value = SpeakerIdentityObservation(
        status="uncertain", reason="speech_too_short", owner_id="o", session_id="s", turn_id="r",
        source=source(session_id="s"), track_id="k1", audio_quality=heard)
    voice = value.voice_ref()
    assert voice.key() == ("o", "s", "r") and (voice.track_id, voice.speech_ms) == ("k1", 450)
    assert compared().voice_ref() is None  # no session, turn or measured speech
    with pytest.raises(ValidationError, match="audio evidence"):
        SpeakerIdentityObservation(status="unavailable", reason="timeout", owner_id="o", track_id="k1")
