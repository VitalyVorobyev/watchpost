# ADR-0008: One React application with a phone layout and a Mac host layout

**Status:** Accepted
**Date:** 2026-08-03

## Context

The product needs two interfaces: a phone UI for status and clips, and a Mac UI that is
"operational rather than feature-rich" — preview, pairing, storage, diagnostics.

The obvious options were a separate native or webview UI for the Mac, or one web application
serving both.

Two codebases would duplicate the API client, the state model, the SSE reconnection logic, the
design tokens, and every status component — and would drift, because the Mac UI would be edited
less often.

## Decision

- One React 19 + TypeScript application, built by Vite, served as static files by the host.
- Two layouts inside it: the phone layout at `/`, and the Mac host layout at `/host`.
- Both consume the same typed API client, the same `useAppState` SSE hook, and the same
  `styles/tokens.css`.
- The Tauri window simply opens `http://127.0.0.1:8787/host`.
- Layout-specific components live in `routes/`; everything shared lives in `components/`.
- The web app never imports `@tauri-apps/api`. It has no knowledge of whether it is running in a
  webview or in Safari — which is what keeps it independently runnable per
  [ADR-0005](0005-python-host-tauri-supervisor.md).

## Consequences

- One state model, one reconnection implementation, one design system. Changes to status
  semantics land in both interfaces at once.
- The Mac layout is reachable from the phone too. Not a problem — it is a diagnostics view, and
  it is behind the same token.
- Bundle size is shared, so the phone downloads a little code it does not use. At this scale the
  difference is negligible.
- Anything genuinely native — menu bar, dock badge, native notifications — cannot live in the web
  app and must be implemented on the Rust side and surfaced through the API. Accepted; the MVP
  needs none of it.
- Vite's dev server proxies `/api` to the host during development, so the client can hot-reload
  against a live camera.
