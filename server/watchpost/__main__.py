"""Command-line entry point.

The server runs standalone from a terminal; the Tauri shell supervises this same process
rather than replacing it. See ADR-0005.
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
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
