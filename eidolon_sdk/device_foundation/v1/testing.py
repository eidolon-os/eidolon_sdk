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

from base64 import urlsafe_b64encode

from .lifecycle import derive_device_instance_id

__all__ = ["named_device_instance_id"]


def named_device_instance_id(label: str) -> str:
    """A valid, stable device instance id for the device a test calls ``label``.

    Distinct labels give distinct devices, and the same label always gives the
    same device, so a test that means "the device we provisioned" and a test
    that means "a device nobody registered" can both keep saying so.
    """

    if not label:
        raise ValueError("a test device needs a name")
    return derive_device_instance_id(urlsafe_b64encode(label.encode()).decode())
