import { useEffect, useState } from "react";
import { api, media } from "../api/client";
import type { AppState, Connection, WatchEvent } from "../api/types";
import { CameraToggle } from "../components/CameraToggle";
import { Preview } from "../components/Preview";
import {
  Banner,
  Card,
  Empty,
  Pill,
  StatusRow,
  activityLabel,
  cameraLabel,
  formatBytes,
  formatDuration,
  formatRelative,
  storageTone,
} from "../components/ui";

export function Home({
  state,
  connection,
  eventTick,
  navigate,
}: {
  state: AppState | null;
  connection: Connection;
  eventTick: number;
  navigate: (path: string) => void;
}) {
  const [latest, setLatest] = useState<WatchEvent | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .events(1)
      .then((events) => !cancelled && setLatest(events[0] ?? null))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [eventTick]);

  const toggle = async () => {
    if (!state) return;
    setBusy(true);
    setError(null);
    try {
      // Optimistic is safe here: the response carries the authoritative state, and a
      // failure is fully recoverable by tapping again.
      await (state.monitoring.armed ? api.disarm() : api.arm());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Command failed");
    } finally {
      setBusy(false);
    }
  };

  if (connection === "offline" || (!state && connection !== "connecting")) {
    return (
      <div className="stack">
        <Banner tone="danger" title="Cannot reach the host">
          Check that your Mac is awake with its lid open, and that this device is on the same
          Wi-Fi network.
        </Banner>
        <Preview state={null} />
      </div>
    );
  }

  if (!state) {
    return <Empty title="Connecting…" body="Waiting for the host to report its status." />;
  }

  const activity = activityLabel(state);
  const camera = cameraLabel(state);
  const armed = state.monitoring.armed;
  const detectorPercent = Math.min(
    100,
    state.detector.threshold > 0 ? (state.detector.score / state.detector.threshold) * 50 : 0,
  );

  return (
    <div className="stack">
      {connection === "reconnecting" && (
        <Banner tone="warn">Connection lost — reconnecting automatically.</Banner>
      )}

      {/* No banner for a switched-off camera. The preview overlay, the badge, the status
          row and the toggle's own label already say so; the banner region is where the
          user looks for *problems*, and this is not one. */}
      {state.capture.status === "on" && state.camera.status !== "ready" && (
        <Banner tone="danger" title="Camera unavailable">
          {state.camera.message ??
            "The host is running but cannot open the camera. Nothing is being recorded."}
        </Banner>
      )}

      {state.storage.status !== "ok" && (
        <Banner tone={state.storage.status === "full" ? "danger" : "warn"} title="Low storage">
          {formatBytes(state.storage.free_bytes)} free.
          {state.storage.status === "full"
            ? " Recording has stopped. Delete some clips to resume."
            : " Old clips will be removed automatically."}
        </Banner>
      )}

      <Preview state={state} />

      <button
        className={`armbtn ${armed ? "armbtn--disarm" : "armbtn--arm"}`}
        onClick={toggle}
        // Not disabled when the camera is off: arming switches it on. Only a camera that
        // is meant to be open but is not working blocks the control.
        disabled={busy || (state.capture.status === "on" && state.camera.status !== "ready")}
      >
        {busy ? <span className="spinner" aria-hidden="true" /> : null}
        {armed ? "Disarm monitoring" : "Arm monitoring"}
      </button>

      <CameraToggle state={state} onError={setError} />

      {error && <Banner tone="danger">{error}</Banner>}

      <Card title="Status">
        <div className="statuslist">
          <StatusRow label="Monitoring">
            <Pill tone={activity.tone}>{activity.text}</Pill>
          </StatusRow>
          <StatusRow
            label="Camera"
            sub={
              state.camera.name
                ? `${state.camera.name}${
                    state.camera.width ? ` · ${state.camera.width}×${state.camera.height}` : ""
                  }`
                : undefined
            }
          >
            <Pill tone={camera.tone}>{camera.text}</Pill>
          </StatusRow>
          <StatusRow
            label="Storage"
            sub={`${state.storage.clips} clip${state.storage.clips === 1 ? "" : "s"} · ${formatBytes(
              state.storage.bytes,
            )}`}
          >
            <Pill tone={storageTone(state.storage.status)}>
              {formatBytes(state.storage.free_bytes)} free
            </Pill>
          </StatusRow>

          {armed && (
            <div>
              <div className="statusrow">
                <span className="statusrow__label">Motion level</span>
                <span className="statusrow__sub">
                  {state.detector.score > state.detector.threshold ? "above" : "below"} threshold
                </span>
              </div>
              <div className="meter" style={{ marginTop: "var(--s2)" }}>
                <div
                  className={`meter__fill ${
                    state.detector.score > state.detector.threshold ? "meter__fill--over" : ""
                  }`}
                  style={{ width: `${detectorPercent}%` }}
                />
              </div>
            </div>
          )}
        </div>
      </Card>

      <Card title="Latest event">
        {latest ? (
          <button className="eventcard" onClick={() => navigate(`/events/${latest.id}`)}>
            {latest.thumb_path ? (
              <img className="eventcard__thumb" src={media.thumb(latest.id)} alt="" />
            ) : (
              <div className="eventcard__thumb" />
            )}
            <div className="eventcard__body">
              <span className="eventcard__time">{formatRelative(latest.started_at)}</span>
              <span className="eventcard__meta">
                {formatDuration(latest.duration_s)} · {latest.trigger}
              </span>
            </div>
            {!latest.viewed && <span className="eventcard__unseen" aria-label="Unviewed" />}
          </button>
        ) : (
          <Empty
            title="No events yet"
            body={
              armed
                ? "Watchpost is watching. A clip will appear here when motion is detected."
                : "Arm monitoring to start recording motion events."
            }
          />
        )}
      </Card>
    </div>
  );
}
