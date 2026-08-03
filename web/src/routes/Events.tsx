import { useEffect, useState } from "react";
import { api, media } from "../api/client";
import type { WatchEvent } from "../api/types";
import {
  Banner,
  Empty,
  formatClock,
  formatDay,
  formatDuration,
  formatBytes,
} from "../components/ui";

const PAGE = 50;

export function Events({
  eventTick,
  navigate,
}: {
  eventTick: number;
  navigate: (path: string) => void;
}) {
  const [events, setEvents] = useState<WatchEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [exhausted, setExhausted] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .events(PAGE)
      .then((list) => {
        if (cancelled) return;
        setEvents(list);
        setExhausted(list.length < PAGE);
      })
      .catch((exc) => !cancelled && setError(exc.message));
    return () => {
      cancelled = true;
    };
  }, [eventTick]);

  const loadMore = async () => {
    if (!events?.length) return;
    setLoadingMore(true);
    try {
      const older = await api.events(PAGE, events[events.length - 1].started_at);
      setEvents([...events, ...older]);
      if (older.length < PAGE) setExhausted(true);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not load more events");
    } finally {
      setLoadingMore(false);
    }
  };

  if (error) return <Banner tone="danger">{error}</Banner>;
  if (!events) return <Empty title="Loading events…" />;
  if (!events.length) {
    return (
      <Empty
        title="No events recorded"
        body="Clips appear here automatically when motion is detected while monitoring is armed."
      />
    );
  }

  // Group by day so a long list stays scannable.
  const groups: { day: string; items: WatchEvent[] }[] = [];
  for (const event of events) {
    const day = formatDay(event.started_at);
    const last = groups[groups.length - 1];
    if (last && last.day === day) last.items.push(event);
    else groups.push({ day, items: [event] });
  }

  return (
    <div className="stack">
      {groups.map((group) => (
        <div key={group.day}>
          <h2 className="daygroup__label">{group.day}</h2>
          <div className="eventlist">
            {group.items.map((event) => (
              <button
                key={event.id}
                className="eventcard"
                onClick={() => navigate(`/events/${event.id}`)}
              >
                {event.thumb_path ? (
                  <img
                    className="eventcard__thumb"
                    src={media.thumb(event.id)}
                    alt=""
                    loading="lazy"
                  />
                ) : (
                  <div className="eventcard__thumb" />
                )}
                <div className="eventcard__body">
                  <span className="eventcard__time">{formatClock(event.started_at)}</span>
                  <span className="eventcard__meta">
                    {formatDuration(event.duration_s)} · {event.trigger} ·{" "}
                    {formatBytes(event.bytes)}
                  </span>
                  {!event.has_clip && (
                    <span className="eventcard__meta" style={{ color: "var(--warn)" }}>
                      Clip unavailable
                    </span>
                  )}
                </div>
                {!event.viewed && <span className="eventcard__unseen" aria-label="Unviewed" />}
              </button>
            ))}
          </div>
        </div>
      ))}

      {!exhausted && (
        <button className="btn btn--block" onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? "Loading…" : "Load older events"}
        </button>
      )}
    </div>
  );
}
