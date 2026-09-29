"""The documents a device signs on the Device Control edge.

Neither of these is ever sent. A device builds the document, signs it, and puts
only the signature on the wire; the Authority rebuilds the same document from
what it already holds and verifies against it. So two implementations that
spell a member differently never learn that from each other — the device is
refused, and the refusal says the signature did not verify, which reads as a
key or transport problem.

That is why these live here and are pinned by
`golden/device-control-configuration-proof.json` rather than by a schema:
nothing validates them at an entry, and a JSON Schema cannot pin member order,
which is the only thing a canonicalisation disagreement changes.

`AssertDeviceManifest.signing_document` in `device_manifest` is the other
document on this edge and already had a definition here; it now has a vector
too (`golden/device-control-manifest-assertion-proof.json`).
"""

from __future__ import annotations

from typing import Any, Literal

from .lifecycle import DeviceRef

#: The operation a device names when it asks the Authority what it should be.
DEVICE_CONTROL_CONFIGURATION_OPERATION = "device-control.configuration"

#: What the ref a configuration answer carries means for the ref a Body holds.
DeviceRefCorrection = Literal["none", "adopt", "refuse"]


def classify_authority_device_ref(
    *,
    held: DeviceRef,
    answered: DeviceRef,
) -> DeviceRefCorrection:
    """Whether a Body takes the ref a `configuration:pull` answer carries.

    The Authority finds the Claim by device identity and answers with the ref
    it holds, so a Body that was re-granted while it kept an older ref is
    corrected here rather than refused forever. That makes the answered ref a
    write to the Body's stored Claim, and this is the rule for when it may be
    one; `golden/device-control-configuration-response.json` pins it for every
    Body that parses the answer.

    Only the Claim's own generations move. Device and Owner Domain are who is
    asking and who answers. The Owner Domain generation changes only when the
    Authority is reset, and a reset is the descriptor's to report, through the
    recovery it requires — a configuration answer handing over a ref at the new
    generation must not let a Body skip that. A re-grant issues the next
    `claim_generation` and restarts `trust_epoch` at one, so `trust_epoch` is
    ordered within one `claim_generation` and never across one: a Body that
    compares the members one by one refuses exactly the re-grant this exists to
    correct. Anything older than what the Body holds is refused.
    """

    if (
        answered.device_instance_id != held.device_instance_id
        or answered.owner_domain_id != held.owner_domain_id
        or answered.owner_domain_generation != held.owner_domain_generation
    ):
        return "refuse"
    answered_order = (answered.claim_generation, answered.trust_epoch)
    held_order = (held.claim_generation, held.trust_epoch)
    if answered_order == held_order:
        return "none"
    return "adopt" if answered_order > held_order else "refuse"


def device_control_configuration_proof_document(
    *,
    device_ref: DeviceRef,
    nonce: str,
) -> dict[str, Any]:
    """What the operational key signs to pull this device's configuration.

    Takes the `DeviceRef` model rather than a mapping: its five members are
    part of the signed bytes, and a caller that assembled them by hand would be
    the second definition this function exists to remove.

    The nonce is echoed in the answer, so the device can tell a reply to this
    question from a replay of the answer to an older one.
    """

    return {
        "device_ref": device_ref.model_dump(mode="json"),
        "nonce": nonce,
        "operation_type": DEVICE_CONTROL_CONFIGURATION_OPERATION,
    }
