/** Turn LAN encryption on or off.
 *
 * Loopback only, and the host enforces that rather than trusting this to hide — `/host` is
 * just a route and a paired phone can open it. Encryption is a security policy affecting
 * every device at once, so it is changed at the machine. See ADR-0011.
 *
 * Both directions need a restart: the certificate is loaded when the socket is created.
 * Both directions also change the URL scheme, which breaks an installed home-screen app,
 * because its launch URL was captured at install time.
 */

import { useState } from "react";
import { api } from "../api/client";
import type { Pairing } from "../api/types";
import { Banner, Card } from "./ui";

export function EncryptionCard({ pairing }: { pairing: Pairing }) {
  const [busy, setBusy] = useState(false);
  const [applied, setApplied] = useState<boolean | null>(null);
  const [confirmOff, setConfirmOff] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const apply = (enabled: boolean) => {
    setBusy(true);
    setError(null);
    api
      .updateSettings({ tls_enabled: enabled })
      .then(() => setApplied(enabled))
      .catch((exc) => setError(exc instanceof Error ? exc.message : "Could not change encryption"))
      .finally(() => {
        setBusy(false);
        setConfirmOff(false);
      });
  };

  if (applied !== null) {
    return (
      <Card title="Encryption">
        <Banner tone="info" title="Restart Watchpost to apply">
          {applied
            ? "The certificate is created at startup. After restarting, every device needs to trust it once — a QR code for that appears here."
            : "After restarting, the host serves plain HTTP again. Devices that trusted the certificate can keep it; it simply stops being used."}{" "}
          The address changes between <code>http</code> and <code>https</code>, so any
          home-screen app has to be removed and added again.
        </Banner>
      </Card>
    );
  }

  return (
    <Card title="Encryption">
      <div className="stack stack--tight">
        {error && <Banner tone="danger">{error}</Banner>}

        {pairing.tls ? (
          confirmOff ? (
            <>
              <Banner tone="warn" title="Turn encryption off?">
                The pairing token and the video go back to being readable by anyone who can
                observe your network — on a WPA2 Wi-Fi, that is everyone who knows the password.
              </Banner>
              <div className="row">
                <button className="btn btn--danger" disabled={busy} onClick={() => apply(false)}>
                  Turn encryption off
                </button>
                <button className="btn btn--ghost" onClick={() => setConfirmOff(false)}>
                  Cancel
                </button>
              </div>
            </>
          ) : (
            <>
              <Banner tone="info">
                Traffic between your devices and this Mac is encrypted with Watchpost&rsquo;s own
                certificate.
              </Banner>
              <button className="btn" onClick={() => setConfirmOff(true)}>
                Turn encryption off
              </button>
              <span className="field__hint">
                Only available on this Mac, and it takes effect after a restart.
              </span>
            </>
          )
        ) : (
          <>
            <Banner tone="warn">
              Traffic is unencrypted. On a WPA2 network anyone who knows the Wi-Fi password can
              read the token and watch the video.
            </Banner>
            <button className="btn" disabled={busy} onClick={() => apply(true)}>
              Turn encryption on
            </button>
            <span className="field__hint">
              Watchpost issues its own certificate. Each device trusts it once, in two steps that
              the setup page explains.
            </span>
          </>
        )}
      </div>
    </Card>
  );
}
