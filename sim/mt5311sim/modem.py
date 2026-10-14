"""The simulated modem: device, line model and fault injection together."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import protocol
from .device import FIRMWARE_750202, Device, DeviceConfig, Firmware, Role
from .faults import Faults, Reply
from .line import Line

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Received:
    """A request the modem received."""

    time: float  # time.monotonic()
    host: bytes
    request: protocol.Request


class Modem:
    """Entry point for transports and tests.

    The transport passes every received message to handle(). Tests change the
    line through `line`, inject faults through `faults` and find every valid
    request in `received`. Hooks registered with on_request() run for every valid
    request before it is answered, so that tests can change the modem at a point
    of the client's traffic instead of at a point in time.
    """

    def __init__(self, firmware: Firmware = FIRMWARE_750202, role: Role = Role.RT,
                 config: DeviceConfig | None = None) -> None:
        self.device = Device(firmware, role, config)
        self.line = Line(self.device)
        self.faults = Faults(self.device)
        self.received: list[Received] = []
        self.hooks: list[Callable[[Received], None]] = []

    def on_request(self, hook: Callable[[Received], None]) -> Callable[[Received], None]:
        """Registers a hook; it can be removed again from `hooks`."""
        self.hooks.append(hook)
        return hook

    def handle(self, host: bytes, message: bytes) -> list[Reply]:
        """Processes one message; returns the replies to send."""
        try:
            request = protocol.decode_request(message)
        except protocol.ProtocolError as e:
            log.debug("ignoring message from %s: %s", host.hex(":"), e)
            return []
        received = Received(time.monotonic(), host, request)
        self.received.append(received)
        for hook in list(self.hooks):
            hook(received)
        return self.faults.respond(host, request)

    def reboot(self, firmware: Firmware | None = None) -> None:
        """Restarts the modem, optionally with another firmware build.

        The session, the line state and all counters are lost; the line comes up
        idle with the same configured values.
        """
        with self.device.lock:
            self.device.load_firmware(firmware or self.device.firmware)
            self.line = Line(self.device, self.line.status)
