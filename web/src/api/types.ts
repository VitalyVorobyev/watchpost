/** Mirrors the state snapshot in docs/design.md section 7. */

export type CameraStatus = "unknown" | "ready" | "disconnected" | "error";
/** Whether the user wants the camera open at all. Separate from CameraStatus, which
 *  describes the device: "off" is an intention, not a fault. */
export type CaptureStatus = "on" | "off";
export type RecordingStatus = "idle" | "recording" | "finalizing" | "cooldown";
export type StorageStatus = "ok" | "warning" | "full";
export type HostStatus = "starting" | "running" | "degraded";

/** Client-side only: how this browser is doing, not how the host is doing. The UI must
 *  never conflate the two — "phone can't reach the Mac" and "Mac can't reach the camera"
 *  look identical if you do. */
export type Connection = "connecting" | "live" | "reconnecting" | "offline";

export interface AppState {
  host: { status: HostStatus; version: string; started_at: number; lan_url: string | null };
  capture: { status: CaptureStatus };
  camera: {
    status: CameraStatus;
    name: string | null;
    uid: string | null;
    width: number | null;
    height: number | null;
    fps: number | null;
    message: string | null;
  };
  monitoring: { armed: boolean; armed_at: number | null };
  recording: { status: RecordingStatus; event_id: string | null; started_at: number | null };
  storage: { status: StorageStatus; clips: number; bytes: number; free_bytes: number };
  detector: { score: number; threshold: number };
  errors: { at: number; code: string; message: string }[];
}

export interface WatchEvent {
  id: string;
  started_at: number;
  ended_at: number;
  duration_s: number;
  trigger: string;
  clip_path: string | null;
  thumb_path: string | null;
  bytes: number;
  peak_score: number;
  viewed: boolean;
  created_at: number;
  has_clip: boolean;
}

export interface Settings {
  camera_name: string | null;
  camera_uid: string | null;
  width: number;
  height: number;
  fps: number;
  sensitivity: number;
  min_area: number;
  pre_roll_s: number;
  post_roll_s: number;
  cooldown_s: number;
  max_clip_s: number;
  retain_max_clips: number;
  retain_max_bytes: number;
  retain_max_age_days: number;
  arm_on_start: boolean;
  capture_enabled: boolean;
  /** Applied at startup, so changing it needs a restart of the host. */
  tls_enabled: boolean;
}

export interface CameraOption {
  name: string;
  uid: string | null;
  selected: boolean;
  /** False for a camera the host remembers but that is not attached right now. Still
   *  selectable — capture picks it up when it comes back. */
  present: boolean;
}

export interface Pairing {
  url: string;
  lan_url: string;
  token: string;
  tls: boolean;
  /** Plaintext page where a device installs the CA. Null when TLS is off. */
  trust_url: string | null;
}

/** Backfill fields a host older than this client does not send.

The host serves the client from `web/dist`, so during development the two drift apart
whenever the client is rebuilt without restarting the server. Reading a field the old host
has never heard of throws during render, and React unmounts the tree — a blank page, with
the real cause only visible in the console. Degrading to a sensible default is always
better than showing nothing.
*/
type HostSnapshot = Omit<AppState, "capture"> & Partial<Pick<AppState, "capture">>;

export function adoptState(raw: HostSnapshot): AppState {
  return {
    ...raw,
    // Predates the capture axis (ADR-0010). Such a host always had the camera open.
    capture: raw.capture ?? { status: "on" },
  };
}
