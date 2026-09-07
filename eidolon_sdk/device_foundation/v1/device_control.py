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

from typing import Any

from .lifecycle import DeviceRef

#: The operation a device names when it asks the Authority what it should be.
DEVICE_CONTROL_CONFIGURATION_OPERATION = "device-control.configuration"


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
