"""Which of this Host's links the product is on, as Ops declared it.

A Host answers on every link it has, and the interface table cannot say what
any of them is *for*. A point-to-point cable between a workstation and a board
is an ordinary /24 to the kernel — indistinguishable from the Wi-Fi the devices
are on. So every component that had to answer "where can my peer find me?"
answered it with "which interfaces do I have", and each of them was wrong in
the same way: on 2026-09-15 the Hub published two A records for one name, a
device took the operations cable's address, and never reached anything again.

The missing fact was never a list of addresses. It was the *role* of a link,
and exactly one place in the system knows it: the Ops host profile, which
names the wire it uploads releases over. This module is the other end of that
declaration — Ops writes it into `/etc/eidolon/host.env`, the sealed Host
profile every Eidolon unit already reads through `EnvironmentFile=`, so nothing
new is plumbed to any of the processes that need it.

What each consumer does with it stays the consumer's own. Admin still offers a
phone every address it has, including the ones on interfaces that are down,
because it says why that is right for a phone; the Hub still publishes A
records for a name and Channel still hands a device candidates to try. The only
thing that moves here is which links are in scope at all.

Two roles, and only the management one is declared, because only it is
declarable: Ops knows the cable's subnet because it configured it, and cannot
know what address a DHCP lease will hand this Host tomorrow. So the product
link is everything not spoken for — which is also what makes an undeclared Host
behave exactly as every Host behaved before this existed.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping, Sequence

#: Where Ops states which of this Host's links carry operations traffic only.
#: A comma-separated list of networks, and the empty string on a Host that
#: declares none — which is every Host that was installed before this existed,
#: and every shipped Host, which has no cable to a workstation at all.
MANAGEMENT_NETWORKS_VARIABLE = "EIDOLON_MANAGEMENT_NETWORKS"

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

__all__ = [
    "MANAGEMENT_NETWORKS_VARIABLE",
    "IPAddress",
    "IPNetwork",
    "HostLinkDeclarationError",
    "declared_management_networks",
    "on_product_link",
]


class HostLinkDeclarationError(ValueError):
    """This Host's link declaration cannot be read, so its roles are unknown."""


def declared_management_networks(
    environ: Mapping[str, str] | None = None,
) -> tuple[IPNetwork, ...]:
    """The links Ops reserved for itself on this Host.

    Read at a composition boundary and passed down, never reached for inside
    the code that filters: a publisher whose answer depends on ambient state is
    one whose answer its caller cannot see — and this is a declaration, fixed
    for the life of the process, not an observation to re-take.

    Unset means a Host that declares nothing, and nothing is what every Host
    declared before any of them could say this, so an older Host keeps working
    against newer code.

    A value that will not parse raises rather than being skipped. Skipping it
    would restore the exact defect this declaration exists to remove, silently
    and only on the Host that has the cable attached; and the only way to get
    one is to hand-edit a file Ops rewrites on every deployment.
    """

    source = os.environ if environ is None else environ
    raw = source.get(MANAGEMENT_NETWORKS_VARIABLE, "")
    networks: list[IPNetwork] = []
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            # Strict, so `10.42.0.2/24` is refused rather than quietly widened
            # to the whole subnet; a bare address is still accepted and means
            # the single host it names, which is what a point-to-point link is.
            networks.append(ipaddress.ip_network(value, strict=True))
        except ValueError as exc:
            raise HostLinkDeclarationError(
                f"{MANAGEMENT_NETWORKS_VARIABLE} names something that is not a network: {value!r}"
            ) from exc
    return tuple(networks)


def on_product_link(address: IPAddress, networks: Sequence[IPNetwork]) -> bool:
    """Whether a peer of the product could be reached at this address.

    Takes a parsed address because every caller already has one: each of them
    had to parse to classify loopback or link-local before it could ask this.

    Mixed families answer without special-casing — an IPv4 address is in no
    IPv6 network — so a Host that reserves a v6 link says nothing about its v4
    addresses, and the reverse.
    """

    return not any(address in network for network in networks)
