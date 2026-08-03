"""Command-line entry point.

The server runs standalone from a terminal; the Tauri shell supervises this same process
rather than replacing it. See ADR-0005.
"""

from __future__ import annotations

import argparse
import json
import logging
import socket
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn

from .api import create_app
from .app import Application, lan_ip
from .enroll import create_enrollment_app, serve_enrollment
from .paths import Paths
from .tls import CA_NAME, ensure_material

DEFAULT_PORT = 8787  # 8765 is taken by another project on the development machine.
# The plaintext certificate helper. Adjacent to the main port so it is easy to remember,
# and only listening while TLS is on. See ADR-0011.
ENROLL_PORT_OFFSET = 1


def _default_web_dist() -> Path | None:
    """Locate the built client relative to the repository layout."""
    candidate = Path(__file__).resolve().parents[2] / "web" / "dist"
    return candidate if candidate.exists() else None


def _port_available(host: str, port: int) -> bool:
    """Whether the port can be bound, checked before anything else happens.

    uvicorn runs the ASGI lifespan *before* it binds its socket, so a second instance
    started by mistake opens the camera, discovers the port is taken, and exits — briefly
    stealing the device from the healthy instance that already owns it. Failing here costs
    one syscall and avoids disturbing anything.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("" if host == "0.0.0.0" else host, port))  # noqa: S104
        except OSError:
            return False
    return True


def _running_host(port: int) -> str | None:
    """The base URL of a Watchpost already serving on this port, or None.

    Both schemes are tried because the running instance decides its own, and a stale
    ``config.json`` is not authoritative about a process that is already up. Certificate
    verification is off deliberately: this is a loopback identity check against a public,
    unauthenticated endpoint, not a trust decision.
    """
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    for scheme in ("http", "https"):
        base = f"{scheme}://127.0.0.1:{port}"
        try:
            with urllib.request.urlopen(f"{base}/healthz", timeout=2, context=context) as response:  # noqa: S310
                if json.load(response).get("ok") is True:
                    return base
        except (urllib.error.URLError, OSError, ValueError):
            continue
    return None


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="watchpost", description="Local-first camera monitor")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the monitoring host")
    serve.add_argument("--host", default="0.0.0.0", help="bind address (default: %(default)s)")  # noqa: S104
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--root", type=Path, default=None, help="storage root override")
    serve.add_argument("--web", type=Path, default=None, help="path to the built web client")
    serve.add_argument(
        "--tls",
        dest="tls",
        default=None,
        action=argparse.BooleanOptionalAction,
        help="serve HTTPS with the self-signed CA (default: the tls_enabled setting)",
    )
    serve.add_argument("-v", "--verbose", action="store_true")

    sub.add_parser("cameras", help="list attached cameras and exit")

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "cameras":
        from .camera import list_devices, supported_modes

        for device in list_devices():
            print(f"[{device.index}] {device.name}  uid={device.uid}")
            for mode in supported_modes(device.index):
                print(f"      {mode.width}x{mode.height} @ {mode.min_fps:g}-{mode.max_fps:g} fps")
        return 0

    _configure_logging(args.verbose)

    if not _port_available(args.host, args.port):
        # Another Watchpost holding the port is not an error: it is already doing the job
        # this command was asked to do. Say where it is and leave it alone — starting a
        # second one would open the camera, fail to bind, and disturb the first on its way
        # out, because uvicorn runs the ASGI lifespan before it binds.
        existing = _running_host(args.port)
        print()
        if existing:
            print(f"  Watchpost is already running on port {args.port}.")
            print(f"    Mac       {existing}/host")
            print('    Stop it   pkill -f "watchpost serve"')
            print()
            return 0
        print(f"  Port {args.port} is held by something that is not Watchpost.")
        print("  Free it, or choose another port with --port.")
        print()
        return 1

    paths = Paths(args.root)
    application = Application(paths, port=args.port)
    ip = lan_ip()
    tls_enabled = args.tls if args.tls is not None else application.config.settings.tls_enabled
    application.tls = tls_enabled
    api = create_app(application, web_dist=args.web or _default_web_dist())

    ssl_args: dict[str, str] = {}
    scheme = "http"

    if tls_enabled:
        material = ensure_material(paths.tls, ip, socket.gethostname().split(".")[0])
        ssl_args = {"ssl_certfile": str(material.cert), "ssl_keyfile": str(material.key)}
        scheme = "https"
        enroll_port = args.port + ENROLL_PORT_OFFSET
        if args.host != "127.0.0.1":
            serve_enrollment(
                create_enrollment_app(material.ca_cert, CA_NAME, ip or "this Mac"),
                args.host,
                enroll_port,
            )

    print()
    print("  Watchpost")
    # The Mac link carries the token too. The host screen is the one that *displays* the
    # pairing QR, so it cannot be paired by scanning one — without this it lands on the
    # pairing prompt and tells the user to scan a code that is never drawn.
    print(f"    Mac       {scheme}://127.0.0.1:{args.port}/host?t={application.tokens.token}")
    if ip and args.host != "127.0.0.1":
        print(f"    Phone     {scheme}://{ip}:{args.port}/?t={application.tokens.token}")
        if tls_enabled:
            print(
                f"    Trust     http://{ip}:{args.port + ENROLL_PORT_OFFSET}/  (first visit only)"
            )
    print(f"    Storage   {paths.root}")
    if not tls_enabled:
        print("    Encrypted no — enable it from the Mac window, or pass --tls")
    print()

    uvicorn.run(api, host=args.host, port=args.port, log_level="warning", **ssl_args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
