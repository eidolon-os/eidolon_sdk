from __future__ import annotations

import ipaddress

import pytest

from eidolon_sdk.system import (
    MANAGEMENT_NETWORKS_VARIABLE,
    HostLinkDeclarationError,
    declared_management_networks,
    on_product_link,
)

#: The failure this declaration exists for: one Host, two links, and a name
#: that answered with both. 10.42.0.2 is the operations cable; 192.168.100.19
#: is the Wi-Fi every device is actually on.
_OPERATIONS_CABLE = "10.42.0.0/24"


def _declared(value: str) -> tuple:
    return declared_management_networks({MANAGEMENT_NETWORKS_VARIABLE: value})


def test_a_host_that_declares_nothing_keeps_every_link_it_has() -> None:
    """Every Host installed before this existed, and every shipped Host."""

    assert declared_management_networks({}) == ()
    assert _declared("") == ()
    assert on_product_link(ipaddress.ip_address("10.42.0.2"), ())


def test_the_operations_cable_is_not_a_link_a_device_is_offered() -> None:
    networks = _declared(_OPERATIONS_CABLE)

    assert not on_product_link(ipaddress.ip_address("10.42.0.2"), networks)
    assert on_product_link(ipaddress.ip_address("192.168.100.19"), networks)


def test_a_bare_address_means_the_one_host_it_names() -> None:
    """A point-to-point cable carries exactly one peer, so /32 is expressible."""

    networks = _declared("10.42.0.2")

    assert networks == (ipaddress.ip_network("10.42.0.2/32"),)
    assert not on_product_link(ipaddress.ip_address("10.42.0.2"), networks)
    assert on_product_link(ipaddress.ip_address("10.42.0.3"), networks)


def test_several_links_may_be_reserved() -> None:
    networks = _declared(f"{_OPERATIONS_CABLE}, fd00:dead::/64")

    assert not on_product_link(ipaddress.ip_address("10.42.0.9"), networks)
    assert not on_product_link(ipaddress.ip_address("fd00:dead::1"), networks)
    assert on_product_link(ipaddress.ip_address("fd00:beef::1"), networks)


def test_reserving_one_family_says_nothing_about_the_other() -> None:
    """An address is in no network of the other version, and does not raise."""

    assert on_product_link(ipaddress.ip_address("10.42.0.2"), _declared("fd00::/64"))
    assert on_product_link(ipaddress.ip_address("fd00::1"), _declared(_OPERATIONS_CABLE))


def test_a_declaration_that_will_not_parse_is_refused_rather_than_skipped() -> None:
    """Skipping it would restore the defect, silently and only on the Host
    that has the cable attached."""

    with pytest.raises(HostLinkDeclarationError):
        _declared("not-a-network")


def test_host_bits_in_a_network_are_refused_rather_than_widened() -> None:
    """`10.42.0.2/24` is a typo for one of two different things, and guessing
    which would either publish the cable or hide a whole product subnet."""

    with pytest.raises(HostLinkDeclarationError):
        _declared("10.42.0.2/24")
