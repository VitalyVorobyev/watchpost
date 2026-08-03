"""Command-line entry point.

The server runs standalone from a terminal; the Tauri shell supervises this same process
rather than replacing it. See ADR-0005.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import uvicorn

from .api import create_app
from .app import Application, lan_ip
from .paths import Paths

DEFAULT_PORT = 8787  # 8765 is taken by another project on the development machine.


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
    api = create_app(application, web_dist=args.web or _default_web_dist())

    ip = lan_ip()
    print()
    print("  Watchpost")
    # The Mac link carries the token too. The host screen is the one that *displays* the
    # pairing QR, so it cannot be paired by scanning one — without this it lands on the
    # pairing prompt and tells the user to scan a code that is never drawn.
    print(f"    Mac      http://127.0.0.1:{args.port}/host?t={application.tokens.token}")
    if ip and args.host != "127.0.0.1":
        print(f"    Phone    http://{ip}:{args.port}/?t={application.tokens.token}")
    print(f"    Storage  {paths.root}")
    print()

    uvicorn.run(api, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
