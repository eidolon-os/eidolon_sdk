"""Authenticate a short-lived observation using the existing runtime trust key.

This is evidence, never a runtime credential or a Memory grant. The audience
and absent runtime_token_version prevent it from being used as a login token.
"""
import hashlib
import time
import jwt
from .speaker_identity import SpeakerIdentityObservation

AUDIENCE = "eidolon-speaker-observation-v1"


def _validate_lifetime(value, now):
    if not (0 < value.expires_at - value.issued_at <= 10
            and value.issued_at <= now + 1 and value.expires_at > now):
        raise ValueError("invalid observation lifetime")
    if value.source is not None and (value.source.session_id != value.session_id
                                    or value.source.request_id != value.turn_id):
        raise ValueError("audio evidence scope mismatch")


def sign_observation(value: SpeakerIdentityObservation, *, secret: str, text: str) -> str:
    if not secret or not value.session_id or not value.turn_id:
        raise ValueError("observation requires runtime scope")
    now = time.time()
    _validate_lifetime(value, now)
    return jwt.encode({"aud": AUDIENCE, "iat": now, "exp": now + 10,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "observation": value.model_dump(mode="json")}, secret, algorithm="HS256")


def verify_observation(token: str, *, secret: str, owner_id: str, session_id: str,
                       turn_id: str, text: str) -> SpeakerIdentityObservation:
    if not secret or not isinstance(token, str) or len(token) > 32768:
        raise ValueError("invalid observation attestation")
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"], audience=AUDIENCE,
            options={"require": ["exp", "iat", "aud"]})
        value = SpeakerIdentityObservation.model_validate(payload["observation"])
        _validate_lifetime(value, time.time())
        if (value.owner_id, value.session_id, value.turn_id) != (owner_id, session_id, turn_id):
            raise ValueError("observation scope mismatch")
        if (payload["exp"] - payload["iat"] > 10 or value.expires_at < time.time()
            or payload["text_sha256"] != hashlib.sha256(text.encode()).hexdigest()):
            raise ValueError("stale or mismatched observation")
        return value
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise ValueError("invalid observation attestation") from None
