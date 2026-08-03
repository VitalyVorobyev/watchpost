# ADR-0003: Disk segment ring for pre-roll, not an in-memory frame buffer

**Status:** Accepted
**Date:** 2026-08-03
**Supersedes:** the "rolling pre-event frame buffer" described in the original `ARCHITECTURE.md`

## Context

An event clip must begin *before* the moment motion was detected. The original architecture
document specified an in-memory rolling buffer of frames, encoded when an event fires.

That approach has real costs. Holding 5 seconds of 720p30 decoded frames is roughly 200 MB of
RAM; keeping them compressed instead means running an encoder anyway. Encoding on the trigger
puts a latency spike exactly where the system is busiest, and the buffer evaporates if the
process crashes — the pre-roll for the event that crashed it is precisely what you wanted.

The standard NVR technique is different: encode continuously into short segments and assemble
clips by concatenation.

## Decision

- `ffmpeg` continuously writes 2-second MPEG-TS segments into a ring directory, with keyframes
  forced at segment boundaries ([ADR-0002](0002-ffmpeg-avfoundation-capture.md)).
- A janitor prunes segments older than `pre_roll_s` plus a safety margin.
- On finalize, the recorder selects every segment overlapping
  `[started_at − pre_roll_s, ended_at + post_roll_s]` and runs
  `ffmpeg -f concat -safe 0 -i list.txt -c copy -movflags +faststart <clip>.mp4`.
- Nothing is re-encoded. `+faststart` moves the MP4 index to the front so iOS Safari can begin
  playback without fetching the whole file.

Note the naming precision this forces: Watchpost *does* encode continuously. What it does not do
is *retain* continuously. The MVP non-goal is worded accordingly in
[`design.md`](../design.md#non-goals-for-the-mvp).

## Consequences

- Pre-roll costs a bounded amount of disk instead of an unbounded amount of RAM, and it survives
  a crash of the Python process because the segments are already on disk.
- Clip creation is a stream copy: near-instant, no CPU spike, no quality loss.
- **Clip boundaries are quantised to the 2-second segment grid.** A clip may begin up to 2 s
  earlier than requested. Accepted; frame-exact boundaries would require re-encoding.
- Segment duration is a real tuning knob: shorter means finer boundaries and more files, longer
  means coarser boundaries and less filesystem churn.
- The ring directory must be excluded from any backup or sync tool — it churns constantly.
- If the disk fills, capture degrades rather than detection. Storage state is therefore part of
  the product state model, not an incidental error.
