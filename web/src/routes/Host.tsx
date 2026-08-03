/** The Mac-side layout.
 *
 * Operational rather than feature-rich: what is the camera doing, how does the phone pair,
 * how much storage is left, and what has recently gone wrong. Same React app as the phone
 * — see ADR-0008.
 */

import { useEffect, useState } from "react";
import qrcode from "qrcode-generator";
import { api } from "../api/client";
import type { AppState, Connection, Pairing } from "../api/types";
import { Preview } from "../components/Preview";
import {
  Banner,
  Card,
  Pill,
  StatusRow,
  activityLabel,
  cameraLabel,
  connectionLabel,
  formatBytes,
  formatClock,
  storageTone,
} from "../components/ui";

function QrCode({ value }: { value: string }) {
  const [dataUrl, setDataUrl] = useState<string | null>(null);

  useEffect(() => {
    // Type 0 lets the library pick the smallest version that fits; "M" tolerates a little
    // screen glare and still scans quickly.
    const qr = qrcode(0, "M");
    qr.addData(value);
    qr.make();
    setDataUrl(qr.createDataURL(8, 0));
  }, [value]);

  if (!dataUrl) return <div className="pairing__qr" />;
  return (
    <div className="pairing__qr">
      <img src={dataUrl} alt="QR code for pairing a phone with this host" />
    </div>
  );
}

export function Host({ state, connection }: { state: AppState | null; connection: Connection }) {
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.pairing().then(setPairing).catch(() => undefined);
  }, []);

  const toggle = async () => {
    if (!state) return;
    setBusy(true);
    try {
      await (state.monitoring.armed ? api.disarm() : api.arm());
    } finally {
      setBusy(false);
    }
  };

  const link = connectionLabel(connection);

  return (
    <div className="stack">
      {!state ? (
        <Banner tone="warn">Waiting for the host…</Banner>
      ) : (
        <>
          <div className="grid-2">
            <div className="stack">
              <Preview state={state} />
              <button
                className={`armbtn ${state.monitoring.armed ? "armbtn--disarm" : "armbtn--arm"}`}
                onClick={toggle}
                disabled={busy || state.camera.status !== "ready"}
              >
                {state.monitoring.armed ? "Disarm monitoring" : "Arm monitoring"}
              </button>
              {state.monitoring.armed && (
                <Banner tone="info" title="Keep the lid open">
                  Watchpost prevents display and idle sleep while armed, but closing the lid
                  suspends the Mac and stops monitoring. No software can prevent that without
                  an external display and power.
                </Banner>
              )}
            </div>

            <div className="stack">
              <Card title="Status">
                <div className="statuslist">
                  <StatusRow label="Monitoring">
                    <Pill tone={activityLabel(state).tone}>{activityLabel(state).text}</Pill>
                  </StatusRow>
                  <StatusRow
                    label="Camera"
                    sub={
                      state.camera.name
                        ? `${state.camera.name}${
                            state.camera.width
                              ? ` · ${state.camera.width}×${state.camera.height}`
                              : ""
                          }`
                        : undefined
                    }
                  >
                    <Pill tone={cameraLabel(state).tone}>{cameraLabel(state).text}</Pill>
                  </StatusRow>
                  <StatusRow label="This window">
                    <Pill tone={link.tone}>{link.text}</Pill>
                  </StatusRow>
                  <StatusRow
                    label="Storage"
                    sub={`${state.storage.clips} clips · ${formatBytes(state.storage.bytes)} used`}
                  >
                    <Pill tone={storageTone(state.storage.status)}>
                      {formatBytes(state.storage.free_bytes)} free
                    </Pill>
                  </StatusRow>
                  <StatusRow label="Version">{state.host.version}</StatusRow>
                </div>
              </Card>

              <Card title="Pair a phone">
                {pairing ? (
                  <div className="pairing">
                    <QrCode value={pairing.url} />
                    <div className="pairing__info stack">
                      <p style={{ margin: 0 }}>
                        Scan with the iPhone camera, then use <strong>Share → Add to Home
                        Screen</strong>.
                      </p>
                      <p className="mono">{pairing.lan_url}</p>
                      <Banner tone="warn">
                        This link contains the access token. Traffic on your network is not
                        encrypted — anyone who can watch it can see the token and the video.
                      </Banner>
                    </div>
                  </div>
                ) : (
                  <p className="field__hint">Loading pairing details…</p>
                )}
              </Card>
            </div>
          </div>

          <Card title="Recent problems">
            {state.errors.length === 0 ? (
              <p className="field__hint" style={{ margin: 0 }}>
                Nothing has gone wrong since the host started.
              </p>
            ) : (
              <div className="errorlog">
                {state.errors.map((entry, index) => (
                  <div className="errorlog__row" key={`${entry.at}-${index}`}>
                    <span className="errorlog__time">{formatClock(entry.at)}</span>
                    <span>
                      <strong>{entry.code}</strong> — {entry.message}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
