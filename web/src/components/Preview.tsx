/** Live camera preview.
 *
 * MJPEG (`multipart/x-mixed-replace`) in an `<img>` is the cheapest live view that works
 * without any client-side decoding. Safari has historically been inconsistent with it, so
 * a snapshot-polling fallback takes over if the stream fails — the preview degrades in
 * quality rather than disappearing.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { media } from "../api/client";
import type { AppState } from "../api/types";
import { Pill, activityLabel } from "./ui";

const SNAPSHOT_INTERVAL_MS = 400;

export function Preview({ state, showBadge = true }: { state: AppState | null; showBadge?: boolean }) {
  const [mode, setMode] = useState<"stream" | "polling">("stream");
  const [failed, setFailed] = useState(false);
  const [src, setSrc] = useState<string>(() => media.preview());
  const timerRef = useRef<number | null>(null);

  const cameraReady = state?.camera.status === "ready";

  const onError = useCallback(() => {
    // One retry as a stream, then fall back to polling stills.
    setMode((current) => {
      if (current === "stream") return "polling";
      setFailed(true);
      return current;
    });
  }, []);

  useEffect(() => {
    if (!cameraReady) {
      if (timerRef.current) window.clearInterval(timerRef.current);
      return;
    }

    if (mode === "stream") {
      setSrc(media.preview());
      setFailed(false);
      return;
    }

    const tick = () => setSrc(`${media.snapshot()}&_=${Date.now()}`);
    tick();
    timerRef.current = window.setInterval(tick, SNAPSHOT_INTERVAL_MS);
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, [mode, cameraReady]);

  const activity = state ? activityLabel(state) : null;

  return (
    <div className="preview">
      {cameraReady && !failed ? (
        <img
          className="preview__img"
          src={src}
          alt="Live camera preview"
          onError={onError}
          decoding="async"
        />
      ) : (
        <div className="preview__overlay">
          {!state ? (
            <>
              <div className="spinner" aria-hidden="true" />
              <span>Connecting to the host…</span>
            </>
          ) : state.camera.status === "disconnected" ? (
            <>
              <strong>Camera disconnected</strong>
              <span>{state.camera.message ?? "Reconnect the camera to resume monitoring."}</span>
            </>
          ) : state.camera.status === "error" ? (
            <>
              <strong>Camera error</strong>
              <span>{state.camera.message ?? "The host could not open the camera."}</span>
            </>
          ) : failed ? (
            <span>Preview unavailable</span>
          ) : (
            <>
              <div className="spinner" aria-hidden="true" />
              <span>Starting the camera…</span>
            </>
          )}
        </div>
      )}

      {showBadge && activity && (
        <Pill tone={activity.tone} className="preview__badge">
          {activity.text}
        </Pill>
      )}
    </div>
  );
}
