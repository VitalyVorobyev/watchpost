import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { CameraOption, Settings as SettingsModel } from "../api/types";
import { Banner, Card, Empty, formatBytes } from "../components/ui";

/** A slider that only writes on release. Sending a PUT for every intermediate value would
 *  hammer the host and, for camera settings, restart capture repeatedly. */
function Slider({
  label,
  hint,
  value,
  min,
  max,
  step,
  format,
  onCommit,
}: {
  label: string;
  hint?: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (value: number) => string;
  onCommit: (value: number) => void;
}) {
  const [local, setLocal] = useState(value);
  useEffect(() => setLocal(value), [value]);

  return (
    <div className="field">
      <div className="field__head">
        <label className="field__label" htmlFor={`f-${label}`}>
          {label}
        </label>
        <span className="field__value">{format(local)}</span>
      </div>
      <input
        id={`f-${label}`}
        type="range"
        min={min}
        max={max}
        step={step}
        value={local}
        onChange={(event) => setLocal(Number(event.target.value))}
        onPointerUp={() => onCommit(local)}
        onKeyUp={() => onCommit(local)}
      />
      {hint && <span className="field__hint">{hint}</span>}
    </div>
  );
}

/** Stable identity for a select option. UID when the host knows one, name otherwise —
 *  ffmpeg reports a name for every device while system_profiler omits some UIDs. */
function cameraValue(camera: CameraOption): string {
  return camera.uid ?? camera.name;
}

export function Settings() {
  const [settings, setSettings] = useState<SettingsModel | null>(null);
  const [cameras, setCameras] = useState<CameraOption[]>([]);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Enumerating spawns ffmpeg and system_profiler, so it is done on demand rather than on
  // a timer. Reconnecting a Continuity Camera is a deliberate act; the user can say when.
  const rescan = useCallback(async () => {
    setScanning(true);
    try {
      setCameras(await api.cameras());
    } catch {
      /* the existing list stays; the camera status pill already reports trouble */
    } finally {
      setScanning(false);
    }
  }, []);

  useEffect(() => {
    api.settings().then(setSettings).catch((exc) => setError(exc.message));
    void rescan();
  }, [rescan]);

  const selectedCamera = cameras.find((camera) => camera.selected);

  const patch = async (update: Partial<SettingsModel>) => {
    setError(null);
    try {
      setSettings(await api.updateSettings(update));
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1500);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not save settings");
    }
  };

  if (error && !settings) return <Banner tone="danger">{error}</Banner>;
  if (!settings) return <Empty title="Loading settings…" />;

  return (
    <div className="stack">
      {error && <Banner tone="danger">{error}</Banner>}
      {saved && <Banner tone="info">Saved.</Banner>}

      <Card title="Camera">
        <div className="field">
          <div className="field__head">
            <label className="field__label" htmlFor="camera">
              Source
            </label>
            <button className="btn btn--quiet" onClick={rescan} disabled={scanning}>
              {scanning ? "Scanning…" : "Rescan"}
            </button>
          </div>
          <select
            id="camera"
            // Driven by the option the host marked selected rather than by the raw setting:
            // the host always includes the configured camera, so the control can never show
            // a different one than capture is using.
            value={selectedCamera ? cameraValue(selectedCamera) : ""}
            onChange={(event) => {
              const chosen = cameras.find((camera) => cameraValue(camera) === event.target.value);
              if (!chosen) return;
              void api.selectCamera(chosen.name, chosen.uid).then((next) => {
                setSettings(next);
                void rescan();
              });
            }}
          >
            {cameras.length === 0 && <option value="">No cameras detected</option>}
            {cameras.map((camera) => (
              <option key={cameraValue(camera)} value={cameraValue(camera)}>
                {camera.name}
                {camera.present ? "" : " — not connected"}
              </option>
            ))}
          </select>
          <span className="field__hint">
            Changing the camera restarts capture. Cameras are remembered by identity, not by
            position, so plugging in another device will not switch the source. A camera that
            is not connected stays in this list and is picked up automatically when it returns
            — Continuity Camera leaves the list whenever the iPhone does.
          </span>
        </div>
      </Card>

      <Card title="Detection">
        <Slider
          label="Sensitivity"
          hint="Higher detects subtler movement, and reacts more to changing light."
          value={settings.sensitivity}
          min={0}
          max={1}
          step={0.05}
          format={(value) => `${Math.round(value * 100)}%`}
          onCommit={(value) => patch({ sensitivity: value })}
        />
        <Slider
          label="Minimum area"
          hint="How much of the frame must change before it counts as motion."
          value={settings.min_area * 100}
          min={0.1}
          max={10}
          step={0.1}
          format={(value) => `${value.toFixed(1)}%`}
          onCommit={(value) => patch({ min_area: value / 100 })}
        />
      </Card>

      <Card title="Recording">
        <Slider
          label="Pre-roll"
          hint="Seconds kept from before the trigger."
          value={settings.pre_roll_s}
          min={0}
          max={30}
          step={1}
          format={(value) => `${value}s`}
          onCommit={(value) => patch({ pre_roll_s: value })}
        />
        <Slider
          label="Post-roll"
          hint="Recording continues this long after motion stops."
          value={settings.post_roll_s}
          min={1}
          max={60}
          step={1}
          format={(value) => `${value}s`}
          onCommit={(value) => patch({ post_roll_s: value })}
        />
        <Slider
          label="Cooldown"
          hint="Quiet period after an event, so one disturbance makes one clip."
          value={settings.cooldown_s}
          min={0}
          max={120}
          step={5}
          format={(value) => `${value}s`}
          onCommit={(value) => patch({ cooldown_s: value })}
        />
        <Slider
          label="Maximum clip length"
          value={settings.max_clip_s}
          min={10}
          max={600}
          step={10}
          format={(value) => `${Math.round(value / 60)}m ${value % 60}s`}
          onCommit={(value) => patch({ max_clip_s: value })}
        />
      </Card>

      <Card title="Retention">
        <p className="field__hint" style={{ marginTop: 0 }}>
          All three limits apply at once. Whichever is reached first removes the oldest clips.
        </p>
        <Slider
          label="Maximum clips"
          value={settings.retain_max_clips}
          min={10}
          max={2000}
          step={10}
          format={(value) => `${value}`}
          onCommit={(value) => patch({ retain_max_clips: value })}
        />
        <Slider
          label="Maximum size"
          value={settings.retain_max_bytes / 1024 ** 3}
          min={1}
          max={200}
          step={1}
          format={(value) => formatBytes(value * 1024 ** 3)}
          onCommit={(value) => patch({ retain_max_bytes: Math.round(value * 1024 ** 3) })}
        />
        <Slider
          label="Maximum age"
          value={settings.retain_max_age_days}
          min={1}
          max={365}
          step={1}
          format={(value) => `${value} day${value === 1 ? "" : "s"}`}
          onCommit={(value) => patch({ retain_max_age_days: value })}
        />
      </Card>

      <Card title="Startup">
        <div className="field">
          <div className="field__head">
            <label className="field__label" htmlFor="arm-on-start">
              Arm when the host starts
            </label>
            <input
              id="arm-on-start"
              type="checkbox"
              checked={settings.arm_on_start}
              onChange={(event) => patch({ arm_on_start: event.target.checked })}
              style={{ width: 22, height: 22, accentColor: "var(--accent)" }}
            />
          </div>
          <span className="field__hint">
            Begin monitoring automatically instead of waiting to be armed.
          </span>
        </div>
      </Card>
    </div>
  );
}
