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
import { CameraToggle } from "../components/CameraToggle";
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

/** The host layout is only a route — a paired phone can open `/host` too. The Quit control
 *  is therefore hidden off-loopback for tidiness, and *enforced* by the host, which answers
 *  403 to a shutdown from anywhere but the Mac itself. */
function isLoopback(): boolean {
  return ["127.0.0.1", "localhost", "::1", "[::1]"].includes(window.location.hostname);
}

export function Host({ state, connection }: { state: AppState | null; connection: Connection }) {
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmQuit, setConfirmQuit] = useState(false);
  const [enabling, setEnabling] = useState(false);
  const [enabled, setEnabled] = useState(false);

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
                disabled={busy || (state.capture.status === "on" && state.camera.status !== "ready")}
              >
                {state.monitoring.armed ? "Disarm monitoring" : "Arm monitoring"}
              </button>
              <CameraToggle state={state} onError={setError} />
              {error && <Banner tone="danger">{error}</Banner>}
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

              {pairing?.trust_url && (
                <Card title="Step 1 — trust this Mac">
                  <div className="pairing">
                    <QrCode value={pairing.trust_url} />
                    <div className="pairing__info stack">
                      <p style={{ margin: 0 }}>
                        Scan this <strong>first</strong>, on each new device. It opens a page
                        that installs the certificate — the page walks you through it, including
                        the separate trust switch that iOS hides under{" "}
                        <strong>General &rsaquo; About</strong>.
                      </p>
                      <p className="mono">{pairing.trust_url}</p>
                      <span className="field__hint">
                        Only the public certificate is served here, over plain HTTP. No access
                        token, because this page cannot yet be encrypted.
                      </span>
                    </div>
                  </div>
                </Card>
              )}

              <Card title={pairing?.trust_url ? "Step 2 — pair a phone" : "Pair a phone"}>
                {pairing ? (
                  <div className="pairing">
                    <QrCode value={pairing.url} />
                    <div className="pairing__info stack">
                      <p style={{ margin: 0 }}>
                        Scan with the iPhone camera, then use <strong>Share → Add to Home
                        Screen</strong>.
                      </p>
                      <p className="mono">{pairing.lan_url}</p>
                      {pairing.tls ? (
                        <Banner tone="info">
                          Encrypted. The link still contains the access token, so treat it like a
                          password — but nobody watching your network can read it or the video.
                        </Banner>
                      ) : (
                        <Banner tone="warn">
                          This link contains the access token. Traffic on your network is not
                          encrypted — anyone who can watch it can see the token and the video.
                        </Banner>
                      )}
                    </div>
                  </div>
                ) : (
                  <p className="field__hint">Loading pairing details…</p>
                )}
              </Card>

              {pairing && !pairing.tls && (
                <Card title="Encryption">
                  <div className="stack stack--tight">
                    <Banner tone="warn">
                      Traffic is unencrypted. On a WPA2 network anyone who knows the Wi-Fi
                      password can read the token and watch the video.
                    </Banner>
                    <button
                      className="btn"
                      disabled={enabling}
                      onClick={() => {
                        setEnabling(true);
                        void api
                          .updateSettings({ tls_enabled: true })
                          .then(() => setEnabled(true))
                          .catch((exc) =>
                            setError(exc instanceof Error ? exc.message : "Could not enable"),
                          )
                          .finally(() => setEnabling(false));
                      }}
                    >
                      Turn encryption on
                    </button>
                    {enabled ? (
                      <Banner tone="info" title="Restart Watchpost to apply">
                        The certificate is created at startup, so the host has to be restarted.
                        Every device then needs to trust it once — a QR code for that appears
                        here afterwards.
                      </Banner>
                    ) : (
                      <span className="field__hint">
                        Watchpost issues its own certificate. Each device trusts it once, in two
                        steps that the setup page explains.
                      </span>
                    )}
                  </div>
                </Card>
              )}
            </div>
          </div>

          {isLoopback() && (
            <Card title="Stop Watchpost">
              {confirmQuit ? (
                <div className="stack stack--tight">
                  <Banner tone="warn">
                    Monitoring stops immediately and the phone loses its connection. Starting it
                    again means coming back to this Mac.
                  </Banner>
                  <div className="row">
                    <button
                      className="btn btn--danger"
                      onClick={() => {
                        // The host dies mid-response, so a network error here is success.
                        void api.shutdown().catch(() => undefined);
                      }}
                    >
                      Shut down the host
                    </button>
                    <button className="btn btn--ghost" onClick={() => setConfirmQuit(false)}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="stack stack--tight">
                  <button className="btn" onClick={() => setConfirmQuit(true)}>
                    Shut down the host
                  </button>
                  <span className="field__hint">
                    Only available on this Mac. The host refuses a shutdown from any other
                    device, so a phone can never lock itself out.
                  </span>
                </div>
              )}
            </Card>
          )}

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
