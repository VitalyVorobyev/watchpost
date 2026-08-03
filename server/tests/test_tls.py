"""Self-signed TLS material.

Every assertion here corresponds to something iOS enforces silently: get one wrong and
Safari refuses the connection with no diagnostic worth reading. See ADR-0011.
"""

from __future__ import annotations

import datetime as dt
import stat

import pytest
from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID

from watchpost.tls import (
    CA_NAME,
    LEAF_DAYS,
    certificate_san_values,
    ensure_material,
    needs_reissue,
    san_values,
)

NOW = dt.datetime(2026, 8, 3, 12, 0, tzinfo=dt.UTC)


def load(path) -> x509.Certificate:
    return x509.load_pem_x509_certificate(path.read_bytes())


class TestSanValues:
    def test_loopback_is_always_covered(self) -> None:
        # The Mac's own window and the Tauri health probe use 127.0.0.1 whatever the
        # network is doing, so a certificate that omits it breaks the host itself.
        assert "127.0.0.1" in san_values(None, None)
        assert "localhost" in san_values(None, None)

    def test_the_bonjour_suffix_is_added_once(self) -> None:
        assert "Mac.local" in san_values(None, "Mac")
        assert "Mac.local" in san_values(None, "Mac.local")
        assert "Mac.local.local" not in san_values(None, "Mac.local")

    def test_the_lan_address_is_included(self) -> None:
        assert "192.168.178.56" in san_values("192.168.178.56", "Mac")

    def test_the_order_is_stable(self) -> None:
        # needs_reissue() compares this against the stored certificate; an unstable order
        # would reissue on every boot and invalidate nothing but the user's patience.
        assert san_values("10.0.0.2", "Mac") == san_values("10.0.0.2", "Mac")
        assert san_values("10.0.0.2", "Mac") == sorted(san_values("10.0.0.2", "Mac"))


class TestGeneratedMaterial:
    @pytest.fixture
    def material(self, tmp_path):
        return ensure_material(tmp_path, "192.168.178.56", "Mac", now=NOW)

    def test_private_keys_are_not_world_readable(self, material, tmp_path) -> None:
        for path in (material.key, tmp_path / "ca.key"):
            assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_the_leaf_stays_inside_apples_validity_limit(self, material) -> None:
        cert = load(material.cert)
        span = cert.not_valid_after_utc - cert.not_valid_before_utc
        assert span.days <= 398, "iOS rejects server certificates valid for over 398 days"
        assert span.days >= LEAF_DAYS - 1

    def test_an_ip_is_an_ipaddress_san_not_a_dnsname(self, material) -> None:
        san = (
            load(material.cert)
            .extensions.get_extension_for_class(x509.SubjectAlternativeName)
            .value
        )
        assert "192.168.178.56" in [str(a) for a in san.get_values_for_type(x509.IPAddress)]
        assert "192.168.178.56" not in san.get_values_for_type(x509.DNSName)

    def test_the_leaf_declares_server_authentication(self, material) -> None:
        eku = load(material.cert).extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        assert ExtendedKeyUsageOID.SERVER_AUTH in eku

    def test_the_leaf_is_not_itself_a_ca(self, material) -> None:
        basic = load(material.cert).extensions.get_extension_for_class(x509.BasicConstraints).value
        assert basic.ca is False

    def test_the_ca_is_a_ca_and_long_lived(self, material) -> None:
        ca = load(material.ca_cert)
        basic = ca.extensions.get_extension_for_class(x509.BasicConstraints).value
        assert basic.ca is True
        assert (ca.not_valid_after_utc - ca.not_valid_before_utc).days > 3000
        assert CA_NAME in ca.subject.rfc4514_string()

    def test_the_leaf_is_signed_by_the_ca(self, material) -> None:
        assert load(material.cert).issuer == load(material.ca_cert).subject


class TestRenewal:
    def test_a_second_call_reuses_both(self, tmp_path) -> None:
        first = ensure_material(tmp_path, "192.168.178.56", "Mac", now=NOW)
        ca_before = first.ca_cert.read_bytes()
        leaf_before = first.cert.read_bytes()

        ensure_material(tmp_path, "192.168.178.56", "Mac", now=NOW)

        assert first.ca_cert.read_bytes() == ca_before
        assert first.cert.read_bytes() == leaf_before

    def test_a_moved_host_gets_a_new_leaf_but_keeps_the_ca(self, tmp_path) -> None:
        """A DHCP lease change must not silently break TLS — but replacing the CA would
        invalidate every device that already trusts it, which is far worse."""
        first = ensure_material(tmp_path, "192.168.178.56", "Mac", now=NOW)
        ca_before = first.ca_cert.read_bytes()
        leaf_before = first.cert.read_bytes()

        ensure_material(tmp_path, "10.0.0.9", "Mac", now=NOW)

        assert first.ca_cert.read_bytes() == ca_before
        assert first.cert.read_bytes() != leaf_before
        assert "10.0.0.9" in certificate_san_values(load(first.cert))

    def test_an_expiring_leaf_is_reissued(self, tmp_path) -> None:
        first = ensure_material(tmp_path, "192.168.178.56", "Mac", now=NOW)
        leaf_before = first.cert.read_bytes()

        ensure_material(
            tmp_path, "192.168.178.56", "Mac", now=NOW + dt.timedelta(days=LEAF_DAYS - 5)
        )
        assert first.cert.read_bytes() != leaf_before

    def test_needs_reissue_is_false_for_a_fresh_matching_certificate(self, tmp_path) -> None:
        material = ensure_material(tmp_path, "192.168.178.56", "Mac", now=NOW)
        wanted = san_values("192.168.178.56", "Mac")
        assert not needs_reissue(load(material.cert), wanted, NOW)

    def test_a_corrupt_leaf_is_replaced_rather_than_crashing_startup(self, tmp_path) -> None:
        material = ensure_material(tmp_path, "192.168.178.56", "Mac", now=NOW)
        material.cert.write_text("not a certificate")

        ensure_material(tmp_path, "192.168.178.56", "Mac", now=NOW)
        assert load(material.cert).issuer == load(material.ca_cert).subject
