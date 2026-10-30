"""Speech voice: what a Companion chose, what a Host can produce, and what a session used.

Three owners, one vocabulary. Data stores the choice (`SpeechVoiceRecord`) and
the Owner's own voices (`OwnerVoice`); Channel knows what the Host's TTS can
produce (`HostVoiceCatalog`) and decides, once per session, which voice is
actually used (`ResolvedSpeechVoice`). Admin only composes the two.

Named "speech voice" on purpose: in this project a bare "voice" already means a
voiceprint.

Vocabulary values travel as plain strings. Channel validates its own catalog
files against the sets below; every reader of the wire tolerates a value it
does not know, so a newer Channel never makes an older reader reject a voice.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# --------------------------------------------------------------------------- vocabulary

GENDERS = ("female", "male", "unspecified")
AGE_BANDS = ("child", "youth", "adult", "senior")
LANGUAGES = {
    "zh-CN": "普通话", "yue": "粤语", "nan": "闽南话", "zh-dongbei": "东北话", "zh-henan": "河南话",
    "zh-hunan": "湖南话", "zh-shaanxi": "陕西话", "zh-shandong": "山东话", "zh-sichuan": "四川话",
    "zh-anhui": "安徽话", "en": "英语", "en-US": "美式英语", "en-GB": "英式英语", "ja": "日语",
    "ko": "韩语", "id": "印尼语",
}
STYLE_LABELS = {
    "bright": "阳光", "lively": "活泼", "sweet": "甜美", "gentle": "温柔", "warm": "温暖",
    "calm": "沉稳", "intellectual": "知性", "elegant": "优雅", "magnetic": "磁性", "cute": "可爱",
    "crisp": "干练", "mature": "成熟", "romantic": "深情", "expressive": "表现力强",
    "playful": "俏皮", "frank": "直爽", "character": "角色音",
}
#: Companions answer in Mandarin; a voice that cannot say it is not offered.
CONVERSATION_LANGUAGE = "zh-CN"


def style_labels(styles: list[str]) -> list[str]:
    """Rendered labels for the keys this release knows; unknown keys are dropped."""
    return [STYLE_LABELS[key] for key in styles if key in STYLE_LABELS]


# --------------------------------------------------------------------------- limits

OWNER_VOICE_LIMIT = 20
DRAFT_LIMIT = 3
DRAFT_TTL_HOURS = 24
DESIGN_PROMPT_MAX_CHARS = 500
PREVIEW_TEXT_MIN_CHARS, PREVIEW_TEXT_MAX_CHARS = 15, 200
RECORDING_MIN_MS, RECORDING_MAX_MS = 10_000, 25_000
UPLOAD_MAX_BYTES, UPLOAD_MAX_MS = 10 * 1024 * 1024, 60_000
REFERENCE_WINDOW_MS = 20_000
REFERENCE_MIN_SPEECH_MS = 5_000
REFERENCE_SAMPLE_RATE = 24_000

Name = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=64)]
Token = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]
OperationId = Annotated[
    str, StringConstraints(strict=True, min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- identity of a voice

class VoiceRef(Contract):
    """One voice of one provider model. Never shown to a client."""

    provider: Token
    model: Token
    voice_id: Token


class OwnerVoiceKey(Contract):
    voice_asset_id: Token


_CATALOG, _OWNER = "c.", "o."


def catalog_voice_key(ref: VoiceRef) -> str:
    raw = json.dumps([ref.provider, ref.model, ref.voice_id], separators=(",", ":")).encode()
    return _CATALOG + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def owner_voice_key(voice_asset_id: str) -> str:
    return _OWNER + voice_asset_id


def decode_voice_key(key: str) -> VoiceRef | OwnerVoiceKey:
    """Inverse of the two encoders. Raises ``ValueError`` for anything else."""
    if key.startswith(_OWNER):
        return OwnerVoiceKey(voice_asset_id=key[len(_OWNER):])
    if key.startswith(_CATALOG):
        body = key[len(_CATALOG):]
        try:
            provider, model, voice_id = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except (binascii.Error, ValueError, TypeError) as exc:
            raise ValueError("malformed voice key") from exc
        return VoiceRef(provider=provider, model=model, voice_id=voice_id)
    raise ValueError("unknown voice key")


# --------------------------------------------------------------------------- the choice (Data)

class CatalogVoiceSelection(Contract):
    source: Literal["catalog"] = "catalog"
    provider: Token
    model: Token
    voice_id: Token
    display_name: Name
    selected_at: datetime | None = None

    @property
    def ref(self) -> VoiceRef:
        return VoiceRef(provider=self.provider, model=self.model, voice_id=self.voice_id)


class OwnerVoiceSelection(Contract):
    source: Literal["owner_voice"] = "owner_voice"
    voice_asset_id: Token
    display_name: Name
    selected_at: datetime | None = None


SpeechVoiceSelection = Annotated[
    CatalogVoiceSelection | OwnerVoiceSelection, Field(discriminator="source")
]


class SpeechVoiceRecord(Contract):
    """The ``speech_voice`` namespace of a Companion's runtime config.

    Absent means the same as ``selection=None``: follow the Host default. The
    default is never written here, so a Host that changes provider is not
    mistaken for an Owner who chose its old default.
    """

    revision: int = Field(ge=0)
    selection: SpeechVoiceSelection | None = None


class SpeechVoiceUpdate(Contract):
    expected_revision: int = Field(ge=0)
    selection: SpeechVoiceSelection | None


# --------------------------------------------------------------------------- the Owner's own voices (Data)

BindingStatus = Literal["deploying", "ready", "rejected", "failed"]


class OwnerVoiceConsent(Contract):
    """Who agreed that this voice may be cloned, and how that was shown."""

    #: ``spoken``: the subject read the consent sentence inside the recording.
    #: ``attested``: an uploaded file; the Owner confirmed the subject agreed.
    method: Literal["spoken", "attested"]
    subject: Literal["self", "other"]
    subject_label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)] | None = None
    consent_version: Token
    statement: Annotated[str, StringConstraints(max_length=200)] | None = None
    allow_re_enrollment: bool = True
    accepted_at: datetime


class OwnerVoiceBinding(Contract):
    """This voice, made on one provider model."""

    provider: Token
    model: Token
    provider_voice_id: Token
    status: BindingStatus
    status_detail: Annotated[str, StringConstraints(max_length=200)] | None = None
    created_at: datetime | None = None
    last_checked_at: datetime | None = None


class OwnerVoice(Contract):
    voice_asset_id: Token
    owner_id: Token
    name: Name
    method: Literal["design", "clone"]
    #: ``draft``: a designed voice the Owner has not kept yet.
    state: Literal["draft", "active"]
    revision: int = Field(ge=1)
    #: The request that created it, so a retried request finds it instead of making another.
    operation_id: OperationId
    #: Companions whose choice is this voice.
    used_by: list[Token] = Field(default_factory=list)
    design_prompt: str | None = None
    design_preview_text: str | None = None
    consent: OwnerVoiceConsent | None = None
    has_reference: bool = False
    has_preview: bool = False
    bindings: list[OwnerVoiceBinding] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    draft_expires_at: datetime | None = None

    def binding_for(self, provider: str, model: str) -> OwnerVoiceBinding | None:
        return next((b for b in self.bindings if (b.provider, b.model) == (provider, model)), None)


class OwnerVoiceCreate(Contract):
    operation_id: OperationId
    name: Name
    method: Literal["design", "clone"]
    state: Literal["draft", "active"]
    design_prompt: Annotated[str, StringConstraints(max_length=DESIGN_PROMPT_MAX_CHARS)] | None = None
    design_preview_text: Annotated[str, StringConstraints(max_length=PREVIEW_TEXT_MAX_CHARS)] | None = None
    consent: OwnerVoiceConsent | None = None
    reference_wav_base64: str | None = None
    preview_wav_base64: str | None = None
    binding: OwnerVoiceBinding


class OwnerVoiceUpdate(Contract):
    expected_revision: int = Field(ge=1)
    name: Name | None = None
    keep: bool = False
    drop_reference: bool = False
    reference_wav_base64: str | None = None


class ProviderVoiceTombstone(Contract):
    """A provider voice nobody uses any more, kept until the provider confirms it is gone."""

    provider: Token
    model: Token
    provider_voice_id: Token
    reason: Literal["deleted", "replaced", "owner_deleted", "draft_expired"]
    created_at: datetime


class OwnerVoiceRuntime(Contract):
    """What a session needs to know about a selected Owner voice, and nothing more."""

    voice_asset_id: Token
    name: Name
    state: Literal["draft", "active"]
    bindings: list[OwnerVoiceBinding]


class CompanionSpeechVoice(Contract):
    """Data's answer for one Companion; the input a resolver needs."""

    companion_id: Token
    revision: int = Field(ge=0)
    selection: SpeechVoiceSelection | None = None
    #: ``invalid``: the stored namespace failed validation; read as no choice.
    record_state: Literal["valid", "invalid"] = "valid"
    owner_voice: OwnerVoiceRuntime | None = None


# --------------------------------------------------------------------------- what the Host can produce (Channel)

class EnrollmentCapabilities(Contract):
    design: bool = False
    clone: bool = False
    #: Who processes the reference audio, for the clone disclosure. ``None`` when local.
    processor: str | None = None


class VoiceOption(Contract):
    voice_key: str
    ref: VoiceRef
    display_name: Name
    summary: str | None = None
    gender: str
    age_band: str
    languages: list[str]
    styles: list[str]
    style_labels: list[str]
    rank: int
    is_host_default: bool = False
    #: The Host default is always listed; it is selectable only if it also meets the rules.
    selectable: bool = True
    curated: bool = True


class HostVoiceCatalog(Contract):
    catalog_revision: str
    state: Literal["fresh", "stale", "degraded"]
    host_selectable: bool
    #: ``single_voice`` or ``no_adapter`` when ``host_selectable`` is false.
    not_selectable_reason: str | None = None
    default_voice_key: str | None = None
    refreshed_at: datetime | None = None
    voices: list[VoiceOption]
    uncurated_available: int = 0
    enrollment: EnrollmentCapabilities = Field(default_factory=EnrollmentCapabilities)

    def option(self, voice_key: str) -> VoiceOption | None:
        return next((v for v in self.voices if v.voice_key == voice_key), None)


# --------------------------------------------------------------------------- what a session uses (Channel)

ResolutionReason = Literal[
    "selected", "same_voice_other_model", "mapped", "unset", "no_equivalent", "host_fixed_voice",
    "invalid_record", "owner_voice", "owner_voice_pending", "owner_voice_rejected",
    "owner_voice_unavailable", "authority_unavailable", "catalog_unavailable", "selected_unverified",
]


class ResolvedSpeechVoice(Contract):
    #: ``None`` means "build TTS exactly as configured": the Host default of a
    #: provider Channel has no adapter for.
    ref: VoiceRef | None
    voice_key: str | None
    display_name: str
    reason: str
    catalog_revision: str | None = None


class ResolveRequest(Contract):
    speech_voice: CompanionSpeechVoice | None = None


# --------------------------------------------------------------------------- making a new voice (Admin ↔ Channel)

class DesignRequest(Contract):
    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=DESIGN_PROMPT_MAX_CHARS)]
    preview_text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=PREVIEW_TEXT_MIN_CHARS, max_length=PREVIEW_TEXT_MAX_CHARS)
    ]


class CloneRequest(Contract):
    reference_wav_base64: str


class EnrolledVoice(Contract):
    binding: OwnerVoiceBinding
    preview_wav_base64: str | None = None


RecordingProblem = Literal[
    "unreadable", "too_large", "too_short", "too_long", "too_little_speech", "too_quiet", "clipping",
]


class ReferenceCheck(Contract):
    """A recording or uploaded file, normalized and measured. The original is not kept."""

    accepted: bool
    problems: list[str]
    duration_ms: int = Field(ge=0)
    window_start_ms: int = Field(ge=0)
    window_ms: int = Field(ge=0)
    speech_ms: int | None = None
    rms: float | None = None
    clipping: float | None = None
    #: The selected window as 24 kHz mono 16-bit WAV.
    wav_base64: str | None = None


__all__ = [name for name in dir() if not name.startswith("_")]
