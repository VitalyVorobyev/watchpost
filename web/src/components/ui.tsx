/** Shared presentational pieces.
 *
 * Status semantics live here so that every screen describes the same state the same way.
 * Each pill carries a text label as well as a colour — colour is never the only signal.
 */

import type { ReactNode } from "react";
import type { AppState, Connection } from "../api/types";

export type Tone = "ok" | "warn" | "danger" | "idle" | "accent";

export function Pill({
  tone,
  children,
  className = "",
}: {
  tone: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={`pill pill--${tone} ${className}`}>
      <span className="pill__dot" aria-hidden="true" />
      {children}
    </span>
  );
}

export function Card({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {title && <h2 className="card__title">{title}</h2>}
      {children}
    </section>
  );
}

export function StatusRow({
  label,
  children,
  sub,
}: {
  label: string;
  children: ReactNode;
  sub?: string;
}) {
  return (
    <div className="statusrow">
      <span className="statusrow__label">{label}</span>
      <span className="statusrow__value">
        {children}
        {sub && <span className="statusrow__sub">{sub}</span>}
      </span>
    </div>
  );
}

export function Empty({
  title,
  body,
  action,
}: {
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <p className="empty__title">{title}</p>
      {body && <p className="empty__body">{body}</p>}
      {action}
    </div>
  );
}

export function Banner({
  tone,
  title,
  children,
}: {
  tone: "warn" | "danger" | "info";
  title?: string;
  children: ReactNode;
}) {
  return (
    <div className={`banner banner--${tone}`} role={tone === "danger" ? "alert" : undefined}>
      <div className="banner__body">
        {title && <strong className="banner__title">{title}</strong>}
        {children}
      </div>
    </div>
  );
}

/* ---- State → words and colour ------------------------------------------ */

export function connectionLabel(connection: Connection): { tone: Tone; text: string } {
  switch (connection) {
    case "live":
      return { tone: "ok", text: "Connected" };
    case "connecting":
      return { tone: "idle", text: "Connecting" };
    case "reconnecting":
      return { tone: "warn", text: "Reconnecting" };
    case "offline":
      return { tone: "danger", text: "Offline" };
  }
}

export function cameraLabel(state: AppState): { tone: Tone; text: string } {
  // Checked before device health: with capture off nothing is observing the device, so
  // whatever health was last seen is stale, and "off" is a choice rather than a fault.
  if (state.capture.status === "off") return { tone: "idle", text: "Off" };
  switch (state.camera.status) {
    case "ready":
      return { tone: "ok", text: "Ready" };
    case "disconnected":
      return { tone: "danger", text: "Disconnected" };
    case "error":
      return { tone: "danger", text: "Error" };
    default:
      return { tone: "idle", text: "Starting" };
  }
}

/** The four situations the UX brief insists must be distinguishable. */
export function activityLabel(state: AppState): { tone: Tone; text: string } {
  if (state.recording.status === "recording") return { tone: "danger", text: "Recording" };
  if (state.recording.status === "finalizing") return { tone: "warn", text: "Saving clip" };
  if (state.recording.status === "cooldown") return { tone: "idle", text: "Cooling down" };
  if (state.capture.status === "off") return { tone: "idle", text: "Camera off" };
  if (!state.monitoring.armed) return { tone: "idle", text: "Disarmed" };
  if (state.camera.status !== "ready") return { tone: "danger", text: "Armed, no camera" };
  return { tone: "ok", text: "Armed, watching" };
}

export function storageTone(status: AppState["storage"]["status"]): Tone {
  return status === "full" ? "danger" : status === "warning" ? "warn" : "idle";
}

/* ---- Formatting -------------------------------------------------------- */

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

export function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return minutes > 0 ? `${minutes}m ${rest}s` : `${rest}s`;
}

export function formatClock(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** "Today" / "Yesterday" / a date — used to group the event list. */
export function formatDay(epochSeconds: number): string {
  const date = new Date(epochSeconds * 1000);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);

  const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (sameDay(date, today)) return "Today";
  if (sameDay(date, yesterday)) return "Yesterday";
  return date.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

export function formatRelative(epochSeconds: number): string {
  const delta = Date.now() / 1000 - epochSeconds;
  if (delta < 60) return "just now";
  if (delta < 3600) return `${Math.floor(delta / 60)} min ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)} h ago`;
  return `${Math.floor(delta / 86400)} d ago`;
}
