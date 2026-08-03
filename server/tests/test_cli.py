"""CLI startup behaviour around an already-running host."""

from __future__ import annotations

import socket

from watchpost.__main__ import _port_available, _running_host


def _bound_port() -> tuple[socket.socket, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock, sock.getsockname()[1]


class TestPortAvailability:
    def test_a_free_port_is_available(self) -> None:
        sock, port = _bound_port()
        sock.close()
        assert _port_available("127.0.0.1", port)

    def test_a_listening_port_is_not(self) -> None:
        """The check exists because uvicorn runs the ASGI lifespan *before* it binds, so a
        duplicate launch opens the camera before discovering the port is taken."""
        sock, port = _bound_port()
        try:
            assert not _port_available("127.0.0.1", port)
        finally:
            sock.close()


class TestRunningHost:
    def test_a_port_held_by_something_else_is_not_a_watchpost(self) -> None:
        # Distinguishing the two is what lets the CLI attach quietly instead of failing.
        sock, port = _bound_port()
        try:
            assert _running_host(port) is None
        finally:
            sock.close()

    def test_nothing_listening_is_not_a_watchpost(self) -> None:
        sock, port = _bound_port()
        sock.close()
        assert _running_host(port) is None
