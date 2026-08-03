import { describe, expect, it } from "vitest";
import type { AppState } from "../api/types";
import { activityLabel, cameraLabel, formatBytes, formatDuration } from "./ui";

function state(overrides: Partial<AppState> = {}): AppState {
  return {
    host: { status: "running", version: "0.1.0", started_at: 0, lan_url: null },
    capture: { status: "on" },
    camera: {
      status: "ready",
      name: "Cam",
      uid: "x",
      width: 1280,
      height: 720,
      fps: 30,
      message: null,
    },
    monitoring: { armed: false, armed_at: null },
    recording: { status: "idle", event_id: null, started_at: null },
    storage: { status: "ok", clips: 0, bytes: 0, free_bytes: 0 },
    detector: { score: 0, threshold: 0.004 },
    errors: [],
    ...overrides,
  };
}

describe("activityLabel", () => {
  // The UX brief requires these four to be visibly distinct — they are easy to
  // conflate, and conflating them makes the product lie about what it is doing.
  it("distinguishes disarmed from armed", () => {
    expect(activityLabel(state()).text).toBe("Disarmed");
    expect(activityLabel(state({ monitoring: { armed: true, armed_at: 1 } })).text).toBe(
      "Armed, watching",
    );
  });

  it("calls out armed-but-no-camera rather than claiming to watch", () => {
    const result = activityLabel(
      state({
        monitoring: { armed: true, armed_at: 1 },
        camera: { ...state().camera, status: "disconnected" },
      }),
    );
    expect(result.text).toBe("Armed, no camera");
    expect(result.tone).toBe("danger");
  });

  it("reports recording", () => {
    const result = activityLabel(
      state({
        monitoring: { armed: true, armed_at: 1 },
        recording: { status: "recording", event_id: "a", started_at: 1 },
      }),
    );
    expect(result.text).toBe("Recording");
    expect(result.tone).toBe("danger");
  });
});

describe("camera off", () => {
  // A deliberate off state and a broken camera must not look alike: one is a choice the
  // user made, the other is a failure they need to act on.
  it("reads as a choice, not a fault", () => {
    const off = state({ capture: { status: "off" } });
    expect(activityLabel(off).text).toBe("Camera off");
    expect(activityLabel(off).tone).not.toBe("danger");
    expect(cameraLabel(off).text).toBe("Off");
    expect(cameraLabel(off).tone).not.toBe("danger");
  });

  it("wins over stale device health, which nothing is observing", () => {
    const off = state({
      capture: { status: "off" },
      camera: { ...state().camera, status: "disconnected" },
    });
    expect(cameraLabel(off).text).toBe("Off");
  });

  it("does not claim to be watching when armed state is stale", () => {
    const off = state({ capture: { status: "off" }, monitoring: { armed: true, armed_at: 1 } });
    expect(activityLabel(off).text).toBe("Camera off");
  });
});

describe("cameraLabel", () => {
  it("maps every camera status to a tone and words", () => {
    for (const status of ["ready", "disconnected", "error", "unknown"] as const) {
      const result = cameraLabel(state({ camera: { ...state().camera, status } }));
      expect(result.text.length).toBeGreaterThan(0);
      expect(result.tone).toBeTruthy();
    }
  });
});

describe("formatBytes", () => {
  it("scales units", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(5 * 1024 ** 3)).toBe("5.0 GB");
  });
});

describe("formatDuration", () => {
  it("splits minutes from seconds", () => {
    expect(formatDuration(24)).toBe("24s");
    expect(formatDuration(90)).toBe("1m 30s");
  });
});
