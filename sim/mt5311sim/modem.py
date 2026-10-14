"""The simulated modem: device, line model and fault injection together."""

from __future__ import annotations

from .device import FIRMWARE_750202, Device, DeviceConfig, Firmware, Role
from .faults import Faults, Reply
from .line import Line


class Modem:
    """Entry point for transports and tests.

    The transport passes every received message to handle(). Tests change the
    line through `line` and inject faults through `faults`.
    """

    def __init__(self, firmware: Firmware = FIRMWARE_750202, role: Role = Role.RT,
                 config: DeviceConfig | None = None) -> None:
        self.device = Device(firmware, role, config)
        self.line = Line(self.device)
        self.faults = Faults(self.device)

    def handle(self, host: bytes, message: bytes) -> list[Reply]:
        return self.faults.handle(host, message)

    def reboot(self, firmware: Firmware | None = None) -> None:
        """Restarts the modem, optionally with another firmware build.

        The session, the line state and all counters are lost; the line comes up
        idle with the same configured values.
        """
        with self.device.lock:
            self.device.load_firmware(firmware or self.device.firmware)
            self.line = Line(self.device, self.line.status)
