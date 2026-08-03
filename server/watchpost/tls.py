"""Self-signed TLS material for the LAN.

There is no certificate authority that will issue for `192.168.x.x` or a `.local` name, so
Watchpost issues its own: a CA generated on first run, and a server certificate signed by it
covering every address the host answers on. The user installs and trusts the CA once per
device. See ADR-0011 for why this route was chosen over a real certificate.

iOS is strict about server certificates and fails the connection with no useful diagnostic
when they are wrong, so the constraints encoded here are not stylistic:

- **at most 398 days of validity** — Apple rejects longer-lived TLS server certificates;
- **subjectAltName is mandatory** — the legacy Common Name is ignored entirely;
- **an IP address must appear as an iPAddress SAN**, not a dNSName;
- **extendedKeyUsage must include serverAuth**.

The CA itself is exempt from the validity limit, and a long-lived CA is the point: it is
what the user installs, and re-installing it annually would be unacceptable. The *leaf* is
therefore reissued automatically as it nears expiry, or whenever the set of addresses
changes — a DHCP lease that moves the Mac must not silently break TLS.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

log = logging.getLogger(__name__)

CA_DAYS = 3650
LEAF_DAYS = 397  # Apple rejects TLS server certificates valid for more than 398 days.
RENEW_BEFORE_DAYS = 30

CA_NAME = "Watchpost Local CA"


@dataclass(frozen=True)
class TlsMaterial:
    """Paths uvicorn and the CA download endpoint need."""

    ca_cert: Path
    cert: Path
    key: Path


def san_values(lan_ip: str | None, local_hostname: str | None) -> list[str]:
    """Every name and address the host should be reachable by, as a stable ordered list.

    Order matters only because it is compared against a stored certificate to decide
    whether reissue is needed; sorting keeps that comparison from flapping.

    ``localhost`` and `127.0.0.1` are always included so the Mac's own window and the
    Tauri shell's health probe work regardless of network state.
    """
    values = {"localhost", "127.0.0.1", "::1"}
    if lan_ip:
        values.add(lan_ip)
    if local_hostname:
        # Bonjour name, which survives a DHCP lease change where an IP does not.
        values.add(
            local_hostname if local_hostname.endswith(".local") else f"{local_hostname}.local"
        )
    return sorted(values)


def _to_general_names(values: list[str]) -> list[x509.GeneralName]:
    names: list[x509.GeneralName] = []
    for value in values:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(value)))
        except ValueError:
            names.append(x509.DNSName(value))
    return names


def certificate_san_values(cert: x509.Certificate) -> list[str]:
    try:
        extension = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return []
    san = extension.value
    return sorted(
        [str(name) for name in san.get_values_for_type(x509.DNSName)]
        + [str(address) for address in san.get_values_for_type(x509.IPAddress)]
    )


def needs_reissue(cert: x509.Certificate, wanted: list[str], now: dt.datetime) -> bool:
    """Whether the leaf must be regenerated.

    Two triggers, both of which have broken working setups in practice: the certificate is
    close enough to expiry that iOS will start refusing it, or the host has moved and the
    certificate no longer covers the address the phone is dialling.
    """
    if certificate_san_values(cert) != wanted:
        return True
    return cert.not_valid_after_utc - now < dt.timedelta(days=RENEW_BEFORE_DAYS)


def _write_private(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
    """Write a private key at mode 0600, created restricted rather than chmod-ed after."""
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(pem)


def _load_ca(
    cert_path: Path, key_path: Path
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    assert isinstance(key, ec.EllipticCurvePrivateKey)
    return cert, key


def _create_ca(
    cert_path: Path, key_path: Path, now: dt.datetime
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, CA_NAME),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Watchpost"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=CA_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _write_private(key_path, key)
    log.info("generated %s (valid %d days)", CA_NAME, CA_DAYS)
    return cert, key


def _create_leaf(
    ca_cert: x509.Certificate,
    ca_key: ec.EllipticCurvePrivateKey,
    sans: list[str],
    cert_path: Path,
    key_path: Path,
    now: dt.datetime,
) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Watchpost host")]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=LEAF_DAYS))
        .add_extension(x509.SubjectAlternativeName(_to_general_names(sans)), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),  # type: ignore[arg-type]
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _write_private(key_path, key)
    log.info("issued host certificate for %s", ", ".join(sans))


def ensure_material(
    directory: Path,
    lan_ip: str | None,
    local_hostname: str | None,
    now: dt.datetime | None = None,
) -> TlsMaterial:
    """Return usable TLS material, creating or renewing only what is needed.

    The CA is created once and then left alone — it is what the user installed, and
    replacing it would silently invalidate every device that trusts it. Only the leaf is
    reissued.
    """
    now = now or dt.datetime.now(dt.UTC)
    material = TlsMaterial(
        ca_cert=directory / "ca.crt",
        cert=directory / "host.crt",
        key=directory / "host.key",
    )
    ca_key_path = directory / "ca.key"

    if material.ca_cert.exists() and ca_key_path.exists():
        ca_cert, ca_key = _load_ca(material.ca_cert, ca_key_path)
    else:
        ca_cert, ca_key = _create_ca(material.ca_cert, ca_key_path, now)

    sans = san_values(lan_ip, local_hostname)
    reissue = True
    if material.cert.exists() and material.key.exists():
        try:
            existing = x509.load_pem_x509_certificate(material.cert.read_bytes())
            reissue = needs_reissue(existing, sans, now)
        except ValueError:
            log.warning("host certificate is unreadable; reissuing")

    if reissue:
        _create_leaf(ca_cert, ca_key, sans, material.cert, material.key, now)

    return material
