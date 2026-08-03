/** Typed client for the local API. */

import { getToken, withToken } from "./token";
import type { AppState, CameraOption, Pairing, Settings, WatchEvent } from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }

  /** The token is missing or wrong — the caller should send the user back to pairing
   *  rather than showing a generic failure. */
  get isAuth(): boolean {
    return this.status === 401;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body) headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    // A network-level failure means the host is unreachable, which is a normal product
    // state (phone left the network, Mac asleep) rather than an exception.
    throw new ApiError("Cannot reach the host", 0);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* body was not JSON; the status text will do */
    }
    throw new ApiError(detail, response.status);
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export const api = {
  state: () => request<AppState>("/state"),
  arm: () => request<AppState>("/command/arm", { method: "POST" }),
  disarm: () => request<AppState>("/command/disarm", { method: "POST" }),

  events: (limit = 50, before?: number) =>
    request<{ events: WatchEvent[] }>(
      `/events?limit=${limit}${before ? `&before=${before}` : ""}`,
    ).then((r) => r.events),

  event: (id: string) =>
    request<{ event: WatchEvent; newer_id: string | null; older_id: string | null }>(
      `/events/${id}`,
    ),

  markViewed: (id: string) => request<{ ok: boolean }>(`/events/${id}/viewed`, { method: "POST" }),
  deleteEvent: (id: string) => request<{ ok: boolean }>(`/events/${id}`, { method: "DELETE" }),

  settings: () => request<Settings>("/settings"),
  updateSettings: (patch: Partial<Settings>) =>
    request<Settings>("/settings", { method: "PUT", body: JSON.stringify(patch) }),

  cameras: () => request<{ cameras: CameraOption[] }>("/cameras").then((r) => r.cameras),
  selectCamera: (name: string, uid: string | null) =>
    request<Settings>("/camera", { method: "PUT", body: JSON.stringify({ name, uid }) }),

  pairing: () => request<Pairing>("/pairing"),
};

/** URLs for elements that cannot send headers. */
export const media = {
  clip: (id: string) => withToken(`${BASE}/clips/${id}.mp4`),
  thumb: (id: string) => withToken(`${BASE}/thumbs/${id}.jpg`),
  preview: () => withToken(`${BASE}/preview.mjpeg`),
  snapshot: () => withToken(`${BASE}/snapshot.jpg`),
  stream: () => withToken(`${BASE}/state/stream`),
};
