"""AF_PACKET transport: connects a modem to a network interface."""

from __future__ import annotations

import heapq
import itertools
import logging
import select
import socket
import threading
import time

from .modem import Modem
from .protocol import ETHERTYPE, RESPONSE_MIN_LEN, pad

log = logging.getLogger(__name__)

MAX_FRAME = 1514


class Transport:
    """Receives EBM frames on an interface and sends the modem's replies.

    Runs in a background thread. Delayed replies are queued, so a delay does not
    hold back the responses to later requests.
    """

    def __init__(self, modem: Modem, interface: str) -> None:
        self.modem = modem
        self.interface = interface
        self._sock: socket.socket | None = None
        self._wake_r, self._wake_w = socket.socketpair()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pending: list[tuple[float, int, bytes, bytes]] = []
        self._order = itertools.count()

    @property
    def mac(self) -> bytes:
        """MAC address of the interface, i.e. the address of the simulated modem."""
        if self._sock is None:
            raise RuntimeError("transport not started")
        # For a bound packet socket the kernel reports the interface's address.
        return self._sock.getsockname()[4]

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("transport already started")
        sock = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(ETHERTYPE))
        sock.bind((self.interface, ETHERTYPE))
        self._sock = sock
        self._thread = threading.Thread(target=self._run, name=f"mt5311sim-{self.interface}")
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._wake_w.send(b"\x00")
        self._thread.join()
        self._thread = None
        assert self._sock is not None
        self._sock.close()
        self._sock = None

    def close(self) -> None:
        self.stop()
        self._wake_r.close()
        self._wake_w.close()

    def __enter__(self) -> Transport:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _run(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            timeout = None
            if self._pending:
                timeout = max(0.0, self._pending[0][0] - time.monotonic())
            readable, _, _ = select.select([self._sock, self._wake_r], [], [], timeout)
            if self._sock in readable:
                self._receive()
            self._send_due()

    def _receive(self) -> None:
        assert self._sock is not None
        message, (_ifname, _proto, pkttype, _hatype, host) = self._sock.recvfrom(MAX_FRAME)
        if pkttype == socket.PACKET_OUTGOING:
            return
        log.debug("<- %s %s", host.hex(":"), message.hex())
        try:
            replies = self.modem.handle(host, message)
        except Exception:
            log.exception("error while handling a message from %s", host.hex(":"))
            return
        now = time.monotonic()
        for reply in replies:
            heapq.heappush(self._pending,
                           (now + reply.delay, next(self._order), host, reply.message))

    def _send_due(self) -> None:
        assert self._sock is not None
        now = time.monotonic()
        while self._pending and self._pending[0][0] <= now:
            _due, _order, host, message = heapq.heappop(self._pending)
            log.debug("-> %s %s", host.hex(":"), message.hex())
            frame = pad(message, RESPONSE_MIN_LEN)
            self._sock.sendto(frame, (self.interface, ETHERTYPE, 0, 0, host))
