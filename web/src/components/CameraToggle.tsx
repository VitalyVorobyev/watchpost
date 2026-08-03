/** Open or release the camera.
 *
 * Deliberately separate from arm/disarm, because they are not the same thing and the
 * difference is invisible otherwise: disarming stops *recording*, but ffmpeg keeps running,
 * the segment ring keeps churning to disk, the camera light stays on, and the live preview
 * stays available to anyone paired. Switching the camera off releases the device.
 */

import { useState } from "react";
import { api } from "../api/client";
import type { AppState } from "../api/types";

export function CameraToggle({
  state,
  onError,
}: {
  state: AppState;
  onError?: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const off = state.capture.status === "off";

  const toggle = async () => {
    setBusy(true);
    try {
      await (off ? api.cameraOn() : api.cameraOff());
    } catch (exc) {
      onError?.(exc instanceof Error ? exc.message : "Could not switch the camera");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack stack--tight">
      <button className="btn btn--block" onClick={toggle} disabled={busy}>
        {busy ? <span className="spinner" aria-hidden="true" /> : null}
        {off ? "Switch the camera on" : "Switch the camera off"}
      </button>
      <span className="field__hint">
        {off
          ? "The camera is released — another application can use it, and nothing is written to disk. Arming switches it back on."
          : "Releases the camera and stops writing to disk. Disarming alone does neither."}
      </span>
    </div>
  );
}
