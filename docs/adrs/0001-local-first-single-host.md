# ADR-0001: Local-first single-host architecture

**Status:** Accepted
**Date:** 2026-08-03

## Context

Watchpost monitors a private space with a camera. The footage is inherently sensitive. The target
user already owns a MacBook and a USB camera and explicitly does not want to deploy a cloud
service or buy dedicated hardware.

Any cloud component — even one used only for signalling or relay — introduces an operator who can
be compelled, breached, or shut down, and creates an account system, a billing question, and a
dependency that makes the product stop working when it lapses.

## Decision

- The MacBook is the sole runtime, the sole data owner, and the local server.
- The phone is a thin client that holds no footage and no durable state beyond a pairing token.
- No external service is contacted at any point in normal operation: no telemetry, no analytics,
  no crash reporting, no update check, no STUN/TURN.
- Everything the product does must work with the LAN's uplink unplugged.

## Consequences

- Remote access outside the LAN is not available and is not a bug. Users who want it must bring
  their own VPN or reverse tunnel.
- There is no multi-device sync, no shared account, and no server-side backup. Losing the Mac
  loses the footage.
- Reliability is bounded by one machine being awake and its lid open — see
  [ADR-0009](0009-ios-platform-constraints.md).
- Testing needs no network fixtures or mock cloud, which keeps the test suite fast and honest.
- Later features that assume a server (push notifications, multi-site) must either be dropped or
  be redesigned to run on the host.
