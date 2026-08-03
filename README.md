# Watchpost

A private, local-first camera monitor. Your MacBook watches a USB camera, records a clip when
something moves, and you check it from your phone. Nothing leaves your network.

- **No cloud.** No account, no subscription, no external service — it works with the internet
  unplugged.
- **Only relevant footage.** Clips include the seconds *before* the trigger, and old footage is
  discarded automatically.
- **Your phone is the remote.** Arm, disarm, and review clips from Safari on the same Wi-Fi.

## Requirements

- macOS with a USB camera (the built-in camera works too)
- [`ffmpeg`](https://ffmpeg.org) — `brew install ffmpeg`
- [`uv`](https://docs.astral.sh/uv/) for the server, [`bun`](https://bun.sh) for the web client
- Rust and `cargo-tauri` if you want the desktop app rather than the terminal

## Run it

```bash
cd web    && bun install && bun run build
cd server && uv sync && uv run watchpost serve
```

Then open the printed URL on your Mac, or scan the QR code with your phone.

For the desktop app instead:

```bash
cargo tauri dev
```

macOS will ask for camera permission the first time. It asks again if you switch between the
terminal and the app — the permission belongs to whichever one launched the capture.

## Where your recordings live

```
~/Library/Application Support/Watchpost/
  clips/     event clips (.mp4)
  thumbs/    thumbnails
  ring/      transient buffer — do not back this up, it churns constantly
  watchpost.db
  config.json
  token      pairing secret, mode 0600
```

Nothing is uploaded anywhere. Deleting an event deletes its clip.

## Things worth knowing

- **The lid must stay open.** Closing it sleeps the Mac and stops monitoring — no software can
  prevent that without an external display and power.
- **Traffic is unencrypted on your LAN.** The pairing token and the video are visible to anyone
  who can watch your local network. TLS is planned; see
  [ADR-0006](docs/adrs/0006-lan-http-token-auth.md).
- **Video only.** No audio is captured or recorded.
- **Motion detection is motion detection.** It will fire on changing light and on pets. Person
  detection is on the roadmap.

## Documentation

[`docs/design.md`](docs/design.md) · [`docs/roadmap.md`](docs/roadmap.md) ·
[`docs/backlog.md`](docs/backlog.md) · [`docs/adrs/`](docs/adrs/)
