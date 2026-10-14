"""Fault injection between the transport and the device.

Rules apply to requests that match a predicate and expire after a number of
matches (count=None: never). They let tests exercise the error handling of
spec sections 6.2 to 6.4: lost and late responses and error responses.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from . import protocol
from .device import Device
from .protocol import ProtocolError, Read, ReadResponse

log = logging.getLogger(__name__)

Predicate = Callable[[protocol.Request], bool]


@dataclass(frozen=True)
class Reply:
    """A response message and the time to wait before sending it."""

    message: bytes
    delay: float = 0.0


def any_request(_request: protocol.Request) -> bool:
    return True


def reads(*addresses: int) -> Predicate:
    """Matches READ requests that contain any of the addresses, or all READs."""
    wanted = set(addresses)

    def match(request: protocol.Request) -> bool:
        if not isinstance(request, Read):
            return False
        return not wanted or any(c.address in wanted for c in request.commands)

    return match


@dataclass
class _Rule:
    kind: str  # "drop", "delay" or "error"
    when: Predicate
    count: int | None
    delay: float = 0.0
    status: int = 0

    def take(self, request: protocol.Request) -> bool:
        """Returns whether the rule applies to request and consumes one use."""
        if self.count == 0 or not self.when(request):
            return False
        if self.count is not None:
            self.count -= 1
        return True


class Faults:
    """Applies fault rules to the requests of a device."""

    def __init__(self, device: Device) -> None:
        self.device = device
        self._lock = threading.Lock()
        self._rules: list[_Rule] = []

    def drop(self, count: int | None = 1, when: Predicate = any_request) -> None:
        """Gives no response to the next count matching requests."""
        self._add(_Rule("drop", when, count))

    def delay(self, seconds: float, count: int | None = 1,
              when: Predicate = any_request) -> None:
        """Sends the response to the next count matching requests after a delay."""
        self._add(_Rule("delay", when, count, delay=seconds))

    def fail_reads(self, addresses: Iterable[int], status: int | None = None,
                   count: int | None = None) -> None:
        """Answers READ requests containing any of the addresses with an error status."""
        error = self.device.config.error_status if status is None else status
        self._add(_Rule("error", reads(*addresses), count, status=error))

    def clear(self) -> None:
        with self._lock:
            self._rules.clear()

    def handle(self, host: bytes, message: bytes) -> list[Reply]:
        """Processes one request; returns the replies to send."""
        try:
            request = protocol.decode_request(message)
        except ProtocolError as e:
            log.debug("ignoring message from %s: %s", host.hex(":"), e)
            return []

        with self._lock:
            if self._take("drop", request):
                return []
            error = self._take("error", request)
            delay = self._take("delay", request)

        response = self.device.respond(host, request)
        if response is None:
            return []
        if error and isinstance(response, ReadResponse):
            response = ReadResponse(response.seq, error.status)
        return [Reply(protocol.encode_response(response), delay.delay if delay else 0.0)]

    def _add(self, rule: _Rule) -> None:
        with self._lock:
            self._rules.append(rule)

    def _take(self, kind: str, request: protocol.Request) -> _Rule | None:
        for rule in self._rules:
            if rule.kind == kind and rule.take(request):
                return rule
        return None
