"""Naming devices in tests without inventing identities they cannot have.

A device instance id is the digest of that device's operational key. Before
that was written down, every test and every contract vector simply typed a
name — ``device-1``, ``box3-lab-1``, ``10:51:db:7e:24:44`` — and each of those
named a device that cannot exist. Hub derived the id from the key and would
have refused all of them; nothing else checked, so the disagreement lived in
the fixtures of six repositories.

Tests still want to say *which* device they mean. This turns the name they
want to use into a real id, through the one derivation, so no repository has to
carry a second version of the rule or eighty characters of hex per fixture.
"""

from __future__ import annotations

from hashlib import sha256

from .lifecycle import DEVICE_INSTANCE_NAMESPACE

__all__ = ["named_device_instance_id"]


def named_device_instance_id(label: str) -> str:
    """A valid, stable device instance id for the device a test calls ``label``.

    Distinct labels give distinct devices, and the same label always gives the
    same device, so a test that means "the device we provisioned" and a test
    that means "a device nobody registered" can both keep saying so.
    """

    if not label:
        raise ValueError("a test device needs a name")
    # Built here rather than routed through the key derivation. This produces a
    # well-formed id for a device that has no key, which is a legitimate thing
    # for a test to want and *not* the thing `derive_device_instance_id` does:
    # feeding it a label base64url-encoded to look like a key taught the
    # derivation to accept anything decodable, and that tolerance is what let a
    # raw point — a real key in the wrong encoding — be hashed into an identity
    # no Authority has a record of.
    return DEVICE_INSTANCE_NAMESPACE + sha256(label.encode()).hexdigest()
