# ADR-0006: LAN HTTP with a bearer token; no TLS in the MVP

**Status:** Accepted
**Date:** 2026-08-03

## Context

The phone must reach the host over the LAN. That requires binding a non-loopback interface, which
means the API is reachable by every device on the network — including devices the user does not
control.

TLS on a LAN is genuinely awkward. There is no public hostname to certify, so the options are a
self-signed certificate (iOS shows a hard interstitial and requires manually trusting a profile
in Settings), a locally-generated CA (same, plus CA distribution), or a real certificate for a
real domain with DNS pointed at a private address (setup far beyond the product's premise).

Each option costs the "minimal setup" promise that justifies the product.

## Decision

For the MVP:

- The server binds `0.0.0.0:8787` over **plain HTTP**.
- A 32-byte random token is generated on first run and stored at mode `0600` under the storage
  root, outside the repository.
- JSON endpoints require `Authorization: Bearer <token>`. Media endpoints (`/clips/*`,
  `/thumbs/*`, `/preview.mjpeg`, `/snapshot.jpg`) *also* accept `?t=<token>`, because `<img>` and
  `<video>` elements cannot set request headers.
- Pairing is a QR code on the Mac host screen encoding `http://<lan-ip>:8787/?t=<token>`. The
  client persists the token to `localStorage` and strips it from the URL.
- `/healthz` is the only unauthenticated endpoint and returns no sensitive data.
- Token comparison uses a constant-time function.

## Consequences

- **Accepted risk:** a LAN attacker who can observe traffic sees both the token and the video.
  The threat model is a home or small-office network, and the alternative costs more usability
  than the risk justifies. This is a deliberate trade, not an oversight.
- Tokens in query strings land in server logs and browser history. Access logging is therefore
  configured to redact `t=`, and the client removes the parameter from the address bar after
  pairing.
- No transport integrity: a LAN attacker could tamper with responses. Out of scope.
- **TLS is on the Phase 2 backlog**, and it is a prerequisite for anything else — Service
  Workers, offline caching, and Web Push all require a secure origin
  ([ADR-0009](0009-ios-platform-constraints.md)).
- There is one token, not per-device tokens, so revocation means rotating for everyone. Fine at
  this scale; revisit alongside TLS.
