# ADR-0002: ffmpeg + AVFoundation for capture and hardware encoding

**Status:** Accepted
**Date:** 2026-08-03

## Context

The host must simultaneously (a) obtain decoded frames for motion detection and live preview and
(b) produce H.264 suitable for browser playback, continuously, at low CPU cost, from one USB
camera.

Options considered:

1. **OpenCV `VideoCapture`** — easy frame access, but pulls in a ~100 MB dependency, gives no
   encoder worth using, and would require a second camera open (or a manual re-encode) for the
   recording path.
2. **PyAV** — good API, but binds a specific FFmpeg build and adds a heavyweight wheel; the
   process-supervision model below is simpler to reason about and to restart.
3. **Native AVFoundation via PyObjC** — most control, most code, and no encoder ergonomics.
4. **A single `ffmpeg` subprocess with two outputs.**

Measured on the target machine (M4 Pro, macOS 26.5.2, ffmpeg 8.1.2, Logitech StreamCam): option 4
runs at 1.0× real time with hardware encoding via `h264_videotoolbox`.

## Decision

One `ffmpeg` process owns the camera and fans out to two outputs:

```
ffmpeg -f avfoundation -framerate 30 -video_size 1280x720 -pixel_format nv12 -i <index>
  -map 0:v -vf "fps=10,scale=480:270" -pix_fmt rgb24 -f rawvideo pipe:1
  -map 0:v -c:v h264_videotoolbox -b:v 4M -color_range mpeg
     -g 60 -force_key_frames "expr:gte(t,n_forced*2)"
     -f segment -segment_time 2 -segment_format mpegts -reset_timestamps 1
     -strftime 1 <ring>/%Y%m%d-%H%M%S.ts
```

- Python reads fixed-size `480·270·3` byte frames from `pipe:1`.
- `-force_key_frames` is aligned to `-segment_time` so every segment opens on a keyframe. This is
  the precondition that makes stream-copy concatenation valid in
  [ADR-0003](0003-segment-ring-preroll.md).
- A supervisor thread restarts `ffmpeg` with exponential backoff and publishes camera health.
- `ffmpeg` is a runtime prerequisite (Homebrew) for the MVP; bundling it as a Tauri sidecar is
  deferred to Phase 2.

## Consequences

- Python dependencies stay small: NumPy and Pillow, no OpenCV, no PyAV.
- The camera is opened exactly once, which avoids macOS multi-client capture quirks.
- Failure handling is process-shaped: a wedged pipeline is fixed by killing and restarting a
  child, not by unwinding library state.
- Frame timestamps come from the host clock at pipe-read time, not from the camera. Detection
  timing is therefore accurate to within one frame interval, which is sufficient for a 2-second
  segment grid but would not be for frame-exact work.
- Errors surface as text on `ffmpeg`'s stderr and must be parsed or logged rather than caught as
  exceptions.
- The user must have `ffmpeg` installed until Phase 2 bundles it.
