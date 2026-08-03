import { useEffect, useState } from "react";
import { api, media } from "../api/client";
import type { WatchEvent } from "../api/types";
import {
  Banner,
  Card,
  Empty,
  StatusRow,
  formatBytes,
  formatClock,
  formatDay,
  formatDuration,
} from "../components/ui";

export function EventDetail({
  id,
  navigate,
}: {
  id: string;
  navigate: (path: string) => void;
}) {
  const [event, setEvent] = useState<WatchEvent | null>(null);
  const [neighbours, setNeighbours] = useState<{ newer: string | null; older: string | null }>({
    newer: null,
    older: null,
  });
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setEvent(null);
    setError(null);
    setConfirmDelete(false);
    api
      .event(id)
      .then((result) => {
        if (cancelled) return;
        setEvent(result.event);
        setNeighbours({ newer: result.newer_id, older: result.older_id });
        if (!result.event.viewed) void api.markViewed(id).catch(() => undefined);
      })
      .catch((exc) => !cancelled && setError(exc.message));
    return () => {
      cancelled = true;
    };
  }, [id]);

  const remove = async () => {
    setDeleting(true);
    try {
      await api.deleteEvent(id);
      navigate("/events");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not delete the event");
      setDeleting(false);
    }
  };

  if (error) {
    return (
      <div className="stack">
        <Banner tone="danger">{error}</Banner>
        <button className="btn btn--block" onClick={() => navigate("/events")}>
          Back to events
        </button>
      </div>
    );
  }

  if (!event) return <Empty title="Loading clip…" />;

  return (
    <div className="stack">
      {event.has_clip ? (
        <video
          className="player"
          src={media.clip(event.id)}
          controls
          playsInline
          preload="metadata"
          poster={event.thumb_path ? media.thumb(event.id) : undefined}
        />
      ) : (
        <Banner tone="warn" title="Clip unavailable">
          The metadata for this event exists but the video file is missing.
        </Banner>
      )}

      <Card title="Event">
        <div className="statuslist">
          <StatusRow label="When" sub={formatDay(event.started_at)}>
            {formatClock(event.started_at)}
          </StatusRow>
          <StatusRow label="Duration">{formatDuration(event.duration_s)}</StatusRow>
          <StatusRow label="Trigger">{event.trigger}</StatusRow>
          <StatusRow label="Size">{formatBytes(event.bytes)}</StatusRow>
        </div>
      </Card>

      <div className="row">
        <button
          className="btn"
          onClick={() => neighbours.newer && navigate(`/events/${neighbours.newer}`)}
          disabled={!neighbours.newer}
        >
          ← Newer
        </button>
        <button
          className="btn"
          onClick={() => neighbours.older && navigate(`/events/${neighbours.older}`)}
          disabled={!neighbours.older}
        >
          Older →
        </button>
      </div>

      <div className="row">
        {event.has_clip && (
          <a className="btn" href={media.clip(event.id)} download={`${event.id}.mp4`}>
            Download
          </a>
        )}
        {/* Destructive, and not recoverable — so it confirms rather than acting optimistically. */}
        {confirmDelete ? (
          <>
            <button className="btn btn--danger" onClick={remove} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete permanently"}
            </button>
            <button className="btn btn--ghost" onClick={() => setConfirmDelete(false)}>
              Cancel
            </button>
          </>
        ) : (
          <button className="btn btn--ghost" onClick={() => setConfirmDelete(true)}>
            Delete
          </button>
        )}
      </div>
    </div>
  );
}
