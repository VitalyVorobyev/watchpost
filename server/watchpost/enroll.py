"""The plaintext helper that hands out the CA certificate.

A device cannot fetch the CA over HTTPS that the CA itself is meant to validate, and iOS
makes clicking through a certificate warning deliberately awkward. So enrolment runs on a
second, plaintext port that serves exactly two things: the CA certificate and the page
explaining what to do with it.

Nothing secret is exposed. A CA certificate is public by construction — it is the *private*
key that matters, and that never leaves the storage root. There is no token here, no API,
no media, and no way to reach the real application from this listener; the phone gets the
pairing URL by scanning the second QR code from the Mac, over HTTPS. See ADR-0011.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

log = logging.getLogger(__name__)

_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trust Watchpost</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 17px/1.5 -apple-system, system-ui, sans-serif;
         margin: 0 auto; padding: 2rem 1.25rem; max-width: 34rem; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 .25rem; }}
  p.lede {{ margin: 0 0 1.75rem; opacity: .7; }}
  ol {{ padding-left: 1.25rem; }}
  li {{ margin-bottom: .85rem; }}
  a.btn {{ display: block; text-align: center; text-decoration: none; padding: .9rem 1rem;
          border-radius: .7rem; background: #3b6fd4; color: #fff; font-weight: 600;
          margin: 0 0 1.75rem; }}
  code {{ background: rgba(127,127,127,.18); padding: .1rem .35rem; border-radius: .3rem; }}
  .note {{ font-size: .9rem; opacity: .7; margin-top: 2rem; }}
</style></head><body>
<h1>Trust this Watchpost</h1>
<p class="lede">One time per device. Afterwards the connection to {host} is encrypted.</p>
<a class="btn" href="/ca.crt">Download the certificate</a>
<ol>
  <li>Tap <strong>Download the certificate</strong> above, then <strong>Allow</strong>.</li>
  <li>Open <strong>Settings</strong>. Near the top you will see
      <strong>Profile Downloaded</strong> — tap it, then <strong>Install</strong>, and enter
      your passcode.</li>
  <li>Still in Settings, go to <strong>General &rsaquo; About &rsaquo; Certificate Trust
      Settings</strong> and switch <strong>{ca_name}</strong> on. This second step is
      separate, and the certificate does nothing without it.</li>
  <li>Return to the Mac and scan the <strong>second</strong> QR code to pair.</li>
</ol>
<p class="note">This page is served without encryption, which is why it contains no access
token — only the public certificate. On a Mac, double-click the downloaded file, find
<code>{ca_name}</code> in Keychain Access, and set it to <em>Always Trust</em>.</p>
</body></html>
"""


def create_enrollment_app(ca_cert: Path, ca_name: str, host_label: str) -> Starlette:
    def page(_request: object) -> HTMLResponse:
        return HTMLResponse(_PAGE.format(host=host_label, ca_name=ca_name))

    def certificate(_request: object) -> Response:
        return Response(
            ca_cert.read_bytes(),
            media_type="application/x-x509-ca-cert",
            headers={"content-disposition": 'attachment; filename="watchpost-ca.crt"'},
        )

    return Starlette(
        routes=[
            Route("/", page),
            Route("/ca.crt", certificate),
            # iOS occasionally prefers the .pem suffix when deciding how to treat a
            # download; serving both costs nothing and avoids a dead end.
            Route("/ca.pem", certificate),
        ]
    )


def serve_enrollment(app: Starlette, host: str, port: int) -> threading.Thread:
    """Run the helper on its own thread so it cannot block the real host."""
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    def run() -> None:
        try:
            server.run()
        except OSError as exc:
            # Losing the helper is survivable: it only matters during enrolment, and the
            # certificate can still be copied from the storage root by hand.
            log.warning("certificate helper could not start on port %d: %s", port, exc)

    thread = threading.Thread(target=run, name="enroll", daemon=True)
    thread.start()
    return thread
