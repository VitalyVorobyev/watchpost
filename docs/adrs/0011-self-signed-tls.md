# ADR-0011 — TLS on the LAN with a self-signed CA

**Status:** Accepted
**Date:** 2026-08-03
**Amends:** [ADR-0006](0006-lan-http-token-auth.md), which accepted plaintext HTTP for the MVP.

## Context

[ADR-0006](0006-lan-http-token-auth.md) accepted plaintext HTTP on the LAN as an MVP risk. The
risk turned out to be concrete rather than theoretical on the development network:

- The network is **WPA2-Personal**. Under WPA2-PSK anyone who knows the Wi-Fi password and
  captures a client's four-way handshake can derive its session key and decrypt its traffic. The
  pairing token and the entire video stream are readable by any guest who has ever been given the
  Wi-Fi password. (WPA3-SAE would give per-session forward secrecy and make this far less
  interesting, but we do not control which network the Mac joins.)
- Plaintext also blocks everything gated on a secure context: **Service Workers and Web Push**,
  which is why notifications sit blocked in Phase 3 ([ADR-0009](0009-ios-platform-constraints.md)).

No public CA will issue a certificate for `192.168.x.x` or a `.local` name, so the options were a
real certificate for a domain we own, or issuing our own.

## Decision

**Watchpost issues its own CA on first run and signs a host certificate with it.**

A real certificate via ACME DNS-01 was rejected despite the nicer user experience: it requires
owning a domain and reaching the internet at issuance and every renewal. That contradicts
[ADR-0001](0001-local-first-single-host.md) — core operation must not depend on an external
service — and would make a house with no internet unable to bring monitoring up.

### Certificate shape

iOS enforces these silently and fails the connection with no useful diagnostic, so they are
encoded in `tls.py` and asserted in `tests/test_tls.py`:

| Requirement | Why |
|---|---|
| ≤ 398 days validity on the **leaf** | Apple rejects longer-lived TLS server certificates |
| `subjectAltName` mandatory | the legacy Common Name is ignored entirely |
| an IP must be an `iPAddress` SAN | a dNSName holding an IP does not match |
| `extendedKeyUsage` includes `serverAuth` | required for TLS server use |

The CA is long-lived (10 years) and exempt from the validity limit. That asymmetry is the point:
the CA is the thing the user installs on each device, and re-installing it annually would be
unacceptable. The **leaf** is reissued automatically when it nears expiry or when the set of
addresses changes, so a DHCP lease that moves the Mac does not silently break TLS. The CA is
never regenerated once it exists — replacing it would invalidate every device that trusts it.

The certificate covers `127.0.0.1`, `::1`, `localhost`, the LAN address, and the Bonjour
`<name>.local`, so the Mac's own window, the Tauri health probe, and the phone all validate
against one certificate.

### Enrolment runs on a separate plaintext port

A device cannot fetch the CA over the HTTPS that CA is meant to validate, and iOS deliberately
makes clicking through a certificate warning awkward. So while TLS is on, a second listener on
`port + 1` serves exactly two things: the CA certificate, and the page explaining the two-step
install that iOS splits across *Settings › Profile Downloaded* and *Settings › General › About ›
Certificate Trust Settings*.

Serving that in plaintext is safe and deliberate. **A CA certificate is public by construction**
— only the private key matters, and it never leaves the storage root at mode `0600`. The
enrolment listener has no token, no API, no media, and no route to the application. The phone
gets its pairing URL by scanning a **second** QR code from the Mac, over HTTPS.

### It is off by default

`tls_enabled` defaults to `false`. Turning it on requires installing and trusting a CA on every
device, so an upgrade must not do it silently and strand a working phone. The host layout offers
it with the consequences stated, and it takes effect on the next start because the certificate is
loaded when the socket is created.

## Consequences

- Setup gains a one-time, per-device step, and it is a fiddly one. The enrolment page exists
  because "install a certificate profile" is not something a user should be left to figure out.
  This is the cost of not depending on a public CA, and it is charged once per device.
- The Mac's own window needs the CA trusted in a *keychain*, not merely present on disk:
  `WKWebView` consults the system trust store and not the certificate the host was configured
  with. An untrusted CA produces an empty window with no error page and nothing in any log, so
  the shell runs `security verify-cert` at startup and prints the exact command when it fails.
  This is the single most confusing failure mode of this decision.
- The Tauri shell reads `tls_enabled` from `config.json` to pick its scheme, and verifies the
  health probe against the CA rather than passing `-k`. A wrong certificate should fail the
  probe, because it is exactly what would break the window.
- `cryptography` becomes a runtime dependency.
- Service Workers and Web Push become *possible*. Neither is implemented; the Phase 3 blocker
  described in [ADR-0009](0009-ios-platform-constraints.md) is lifted, not resolved.
- ADR-0006's threat model still holds for the token itself: it is a bearer credential shared by
  every device, and TLS protects it in transit without making it any less a shared secret.
