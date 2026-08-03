/** Live host state over SSE, with automatic reconnection.
 *
 * This is the single source of truth for the client, mirroring the host's own rule: every
 * screen observes this state rather than tracking its own copy.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { media } from "./client";
import { bootstrapToken, getToken } from "./token";
import type { AppState, Connection, WatchEvent } from "./types";

const BACKOFF_MS = [1000, 2000, 4000, 8000, 15000];

export interface LiveState {
  state: AppState | null;
  connection: Connection;
  /** Bumped whenever the host announces a new event, so lists know to refetch. */
  eventTick: number;
  latestEvent: WatchEvent | null;
  needsToken: boolean;
}

export function useAppState(): LiveState {
  const [state, setState] = useState<AppState | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [eventTick, setEventTick] = useState(0);
  const [latestEvent, setLatestEvent] = useState<WatchEvent | null>(null);
  const [needsToken, setNeedsToken] = useState(false);

  const sourceRef = useRef<EventSource | null>(null);
  const attemptRef = useRef(0);
  const timerRef = useRef<number | null>(null);

  const connect = useCallback(() => {
    if (!getToken()) {
      setNeedsToken(true);
      setConnection("offline");
      return;
    }

    sourceRef.current?.close();
    const source = new EventSource(media.stream());
    sourceRef.current = source;

    source.onopen = () => {
      attemptRef.current = 0;
      setConnection("live");
      setNeedsToken(false);
    };

    source.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === "state") {
          setState(message.state as AppState);
          setConnection("live");
        } else if (message.type === "event") {
          setLatestEvent(message.event as WatchEvent);
          setEventTick((tick) => tick + 1);
        }
      } catch {
        /* a malformed frame is not worth tearing the stream down for */
      }
    };

    source.onerror = () => {
      source.close();
      // EventSource cannot report the HTTP status, so a bad token and an unreachable host
      // look the same here. A probe distinguishes them, because that difference is exactly
      // what the user needs to be told.
      setConnection(attemptRef.current === 0 ? "reconnecting" : "offline");
      void fetch(`/api/v1/state`, {
        headers: { Authorization: `Bearer ${getToken() ?? ""}` },
      })
        .then((response) => {
          if (response.status === 401) setNeedsToken(true);
        })
        .catch(() => {
          /* host unreachable — the backoff below handles it */
        });

      const delay = BACKOFF_MS[Math.min(attemptRef.current, BACKOFF_MS.length - 1)];
      attemptRef.current += 1;
      timerRef.current = window.setTimeout(connect, delay);
    };
  }, []);

  useEffect(() => {
    bootstrapToken();
    connect();

    // iOS suspends timers and connections in a backgrounded tab; returning to the app
    // must reconnect immediately rather than waiting out a backoff that never ticked.
    const onVisible = () => {
      if (document.visibilityState === "visible" && sourceRef.current?.readyState !== 1) {
        attemptRef.current = 0;
        connect();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onVisible);

    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onVisible);
      if (timerRef.current) window.clearTimeout(timerRef.current);
      sourceRef.current?.close();
    };
  }, [connect]);

  return { state, connection, eventTick, latestEvent, needsToken };
}
