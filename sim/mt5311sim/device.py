"""Protocol endpoint of the simulated modem: DSP memory and session handling."""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum

from . import protocol, words
from .protocol import (
    ConnectResponse,
    ConnectStage1,
    ConnectStage2,
    Disconnect,
    ProtocolError,
    Read,
    ReadResponse,
    Space,
    Status,
)
from .registers import Layout, Register, register

log = logging.getLogger(__name__)

# Constant tables used by the layout check (8.2): Xdsl2Band codes of the band table
# and Xdsl2Unit codes of the channel table.
LINE_BANDS = (3, 5, 7, 9, 11, 4, 6, 8, 10, 1, 2)
CHANNEL_UNITS = (1, 1, 2, 2)

BOARD_TYPE = 0x801568  # observed; bits 7-0: 0x68 = MT5311 SFP
SIGNATURE = b"GAT"
CHIP_BITS = 0x000028  # bits of xdslTerminal observed on an AURORA chip besides bit 0

_SPACES = frozenset(Space)


@dataclass(frozen=True)
class Firmware:
    version: int
    date: str  # MMDDYY
    time: str  # hhmmss
    layout: Layout | None  # None: a build whose layout matches neither known layout


# Firmware 750202 is the build verified on a device. The version word of the branch
# 1.61 build is not known; xdslFirmwareVer does not identify the layout (8.2).
FIRMWARE_750202 = Firmware(0x750202, "090718", "173044", Layout.BRANCH_160)
FIRMWARE_BRANCH_161 = Firmware(0x750202, "080217", "190152", Layout.BRANCH_161)
FIRMWARE_UNKNOWN = Firmware(0x760101, "010124", "120000", None)


class Role(IntEnum):
    OT = 0
    RT = 1


class LineState(IntEnum):
    IDLE = 0
    HANDSHAKE = 1
    TRAINING = 2
    SHOWTIME = 3


def terminal_word(role: Role, state: LineState) -> int:
    """Value of xdslTerminal (9.2.1)."""
    return CHIP_BITS | role | (state << 8)


@dataclass
class DeviceConfig:
    """Behaviour that the specification leaves open (6.4)."""

    read_without_session: bool = True
    error_status: int = 0x01


class Device:
    """A simulated MT5311 that answers EBM requests from its DSP memory.

    All methods are thread-safe. Callers that need several changes to appear
    atomically to the protocol side hold `lock` around them.
    """

    def __init__(self, firmware: Firmware = FIRMWARE_750202, role: Role = Role.RT,
                 config: DeviceConfig | None = None) -> None:
        self.lock = threading.RLock()
        self.config = config or DeviceConfig()
        self.role = role
        self.memory: dict[int, int] = {}
        self._pending_host: bytes | None = None
        self._session_host: bytes | None = None
        self.load_firmware(firmware)

    # Memory

    @property
    def layout(self) -> Layout | None:
        return self.firmware.layout

    def peek(self, address: int) -> int:
        with self.lock:
            return self.memory.get(address, 0)

    def poke(self, address: int, word: int) -> None:
        with self.lock:
            self.memory[address] = words.unsigned(word)

    def get(self, name: str) -> list[int]:
        """Reads all words of a register."""
        with self.lock:
            base = self._address(register(name))
            return [self.peek(base + i) for i in range(register(name).words)]

    def set(self, name: str, value: int | Sequence[int]) -> None:
        """Writes a register; multi-word registers take one word per element."""
        reg = register(name)
        values = [value] if isinstance(value, int) else list(value)
        if len(values) != reg.words:
            raise ValueError(f"{name} has {reg.words} words, got {len(values)}")
        with self.lock:
            base = self._address(reg)
            for i, word in enumerate(values):
                self.poke(base + i, word)

    def _address(self, reg: Register) -> int:
        if reg.addr_160 == reg.addr_161:
            return reg.addr_160
        if self.layout is None:
            raise LookupError(f"{reg.name}: firmware has no known address layout")
        return reg.address(self.layout)

    # Identification

    def load_firmware(self, firmware: Firmware) -> None:
        """Replaces the memory with the initial content of a firmware build."""
        with self.lock:
            self.firmware = firmware
            self.memory.clear()
            self.end_session()

            id_block = {
                "xdslFirmwareVer": firmware.version,
                "xdslFirmwareDate": words.bcd(firmware.date),
                "xdslFirmwareTime": words.bcd(firmware.time),
                "xdslBoardType": BOARD_TYPE,
                "xdslTerminal": terminal_word(self.role, LineState.IDLE),
                "xdslMetanoiaSignature": words.octets(SIGNATURE, 1)[0],
            }
            for name, word in id_block.items():
                self.set(name, word)

            if firmware.layout is not None:
                for i, band in enumerate(LINE_BANDS):
                    self.set(f"xdsl2LineBand{i}", band)
                for i, unit in enumerate(CHANNEL_UNITS):
                    self.set(f"xdsl2ChStatusUnit{i}", unit)

    # Session

    @property
    def session_host(self) -> bytes | None:
        return self._session_host

    def end_session(self) -> None:
        with self.lock:
            self._pending_host = None
            self._session_host = None

    def handle(self, host: bytes, message: bytes) -> bytes | None:
        """Processes one request from host (MAC address); returns the response or None."""
        try:
            request = protocol.decode_request(message)
        except ProtocolError as e:
            log.debug("ignoring message from %s: %s", host.hex(":"), e)
            return None

        response = self.respond(host, request)
        return None if response is None else protocol.encode_response(response)

    def respond(self, host: bytes, request: protocol.Request) -> protocol.Response | None:
        """Processes one decoded request from host; returns the response or None."""
        with self.lock:
            return self._dispatch(host, request)

    def _dispatch(self, host: bytes, request: protocol.Request) -> protocol.Response | None:
        match request:
            case ConnectStage1(seq):
                self._pending_host = host
                return ConnectResponse(seq, 1)
            case ConnectStage2(seq) if host in (self._pending_host, self._session_host):
                self._session_host = host
                return ConnectResponse(seq, 2)
            case ConnectStage2():
                return None
            case Read() if host == self._session_host or self.config.read_without_session:
                return self._read(request)
            case Read():
                return None
            case Disconnect():
                if host == self._session_host:
                    self.end_session()
                return None

    def _read(self, request: Read) -> ReadResponse:
        values = []
        for command in request.commands:
            if command.space not in _SPACES or command.count != protocol.WORD_BYTES:
                return ReadResponse(request.seq, self.config.error_status)
            # Only space X is simulated; Y and P read as zero.
            values.append(self.peek(command.address) if command.space == Space.X else 0)
        return ReadResponse(request.seq, Status.OK, tuple(values))
