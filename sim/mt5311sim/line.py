"""Model of the VDSL2 line of the simulated modem.

The model keeps the line state and its values in physical units and writes them
into the device memory in the encodings of the specification (sections 7 and 9).
Time only advances through tick(), so tests are deterministic.

Counters are maintained for an RT device (9.1): index 0 of the vendor counter table
is the downstream (near-end), index 1 the upstream (far-end).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from . import words
from .device import Device, LineState, Role, terminal_word

MODEM_STATUS_SHOWTIME = 0x00000F
MODEM_STATUS_OTHER = 0x000011  # observed outside showtime (9.2.2)

INTERVAL_15M = 15 * 60
INTERVAL_1DAY = 24 * 60 * 60

PROFILES = ("8a", "8b", "8c", "8d", "12a", "12b", "17a", "30a")
TRANS_SYS_VDSL2_EUROPE = 57
TPS_TC_PTM = 0x000020
TWCONFIG3_ASCII_VERSION = 1 << 19

TRUE, FALSE = 1, 2  # TruthValue
SNR_MODE_DISABLED, SNR_MODE_ENABLED = 1, 2


class FailureReason(IntEnum):
    """Cause of the last loss of showtime (9.4)."""

    NONE = 0
    LOSS_OF_SIGNAL = 1
    LOSS_OF_POWER = 2
    CRC_ERRORS = 3
    TRAINING_FAILURE = 4
    DISCONNECT = 5
    SNR_BELOW_MINIMUM = 6


@dataclass
class Band:
    """Status of one band; None is written as 'not applicable' (7FFFFE)."""

    line_attenuation: float | None = None  # dB
    signal_attenuation: float | None = None  # dB
    snr_margin: float | None = None  # dB


@dataclass
class Direction:
    data_rate: int  # kbit/s
    attainable_rate: int  # kbit/s
    transmit_power: float  # dBm
    delay: int = 0  # ms
    inp: float = 0.0  # symbols
    interleave_depth: int = 1
    interleave_block: int = 255
    trellis: bool = True
    virtual_noise: bool = False
    total: Band = field(default_factory=Band)  # band index 10 (DS) or 9 (US)
    bands: list[Band | None] = field(default_factory=list)  # DS1-DS4 or US0-US4
    tones: list[tuple[int, int]] = field(default_factory=list)  # visible passbands


def _default_downstream() -> Direction:
    return Direction(
        data_rate=100000, attainable_rate=116000, transmit_power=12.8,
        total=Band(25.9, 25.1, 3.3),
        bands=[Band(12.0, 12.0, 3.3), Band(30.0, 29.8, 3.3), Band(48.1, 47.9, 3.4), None],
        tones=[(33, 859), (1216, 1971), (2783, 4095)],
    )


def _default_upstream() -> Direction:
    # On an RT device the upstream totals of attenuation read 7FFFFE (9.1).
    return Direction(
        data_rate=40000, attainable_rate=44000, transmit_power=-2.9,
        total=Band(None, None, 6.0),
        bands=[None, Band(15.2, 15.0, 6.1), Band(36.4, 36.3, 6.0), Band(55.0, 54.8, 6.0),
               None],
        tones=[(870, 1205), (1972, 2782), (4096, 5000)],
    )


@dataclass
class LineStatus:
    """Values that are valid in showtime."""

    downstream: Direction = field(default_factory=_default_downstream)
    upstream: Direction = field(default_factory=_default_upstream)
    profile: str = "17a"
    trans_sys: int = TRANS_SYS_VDSL2_EUROPE
    tps_tc: int = TPS_TC_PTM
    electrical_length: float = 12.5  # dB
    peer_vendor_id: bytes = bytes.fromhex("b500") + b"BDCM" + bytes.fromhex("1cc0")
    own_vendor_id: bytes = bytes.fromhex("b500") + b"META"
    peer_version: str = "1.0.0"
    own_version: str = "1_58_2_30"


@dataclass
class Counters:
    """Error counters of one direction, unbounded; written modulo 2^24."""

    crc: int = 0
    fec: int = 0


@dataclass
class _Interval:
    """Current 15-minute or 1-day interval of the performance monitoring counters."""

    length: int
    elapsed: int = 0
    # Per PML index (0 = US, 1 = DS): FEC seconds, errored seconds, unavailable seconds
    fecs: list[int] = field(default_factory=lambda: [0, 0])
    es: list[int] = field(default_factory=lambda: [0, 0])
    uas: list[int] = field(default_factory=lambda: [0, 0])
    full_inits: int = 0
    # Per direction ("us", "ds"): CRC and FEC counts of the channel
    errors: dict[str, Counters] = field(
        default_factory=lambda: {"us": Counters(), "ds": Counters()})


class Line:
    """Line state, values and counters of a device; writes them into its memory."""

    def __init__(self, device: Device) -> None:
        self.device = device
        self.state = LineState.IDLE
        self.status = LineStatus()
        self.failure_reason = FailureReason.NONE
        self.showtime_seconds = 0
        # Errors per second while in showtime, per direction ("ds", "us").
        self.error_rates = {"ds": Counters(), "us": Counters()}
        self.totals = {"ds": Counters(), "us": Counters()}
        self.current = {"ds": Counters(), "us": Counters()}
        self.intervals = {"15M": _Interval(INTERVAL_15M), "1Day": _Interval(INTERVAL_1DAY)}
        self._write_all()

    # State changes

    def set_state(self, state: LineState) -> None:
        with self.device.lock:
            if self.state == LineState.IDLE and state != LineState.IDLE:
                for interval in self.intervals.values():
                    interval.full_inits += 1
            if state == LineState.SHOWTIME and self.state != LineState.SHOWTIME:
                self.showtime_seconds = 0
                self.current = {"ds": Counters(), "us": Counters()}
            self.state = state
            self._write_all()

    def showtime(self) -> None:
        """Brings the line into showtime with the values in `status`."""
        self.set_state(LineState.SHOWTIME)

    def retrain(self, reason: FailureReason, state: LineState = LineState.IDLE) -> None:
        """Leaves showtime and records the reason (9.4)."""
        with self.device.lock:
            self.failure_reason = reason
            self.set_state(state)

    def apply_status(self) -> None:
        """Writes changes made to `status` while the line stays in its state."""
        with self.device.lock:
            self._write_all()

    # Time and counters

    def tick(self, seconds: int = 1) -> None:
        with self.device.lock:
            for _ in range(seconds):
                self._second()
            self._write_all()

    def add_errors(self, direction: str, *, crc: int = 0, fec: int = 0) -> None:
        """Adds error events at once, without counting errored seconds."""
        with self.device.lock:
            self._count(direction, crc, fec)
            self._write_all()

    def _second(self) -> None:
        if self.state == LineState.SHOWTIME:
            self.showtime_seconds += 1
            for direction, index in (("us", 0), ("ds", 1)):
                rate = self.error_rates[direction]
                self._count(direction, rate.crc, rate.fec)
                for interval in self.intervals.values():
                    interval.es[index] += int(rate.crc > 0)
                    interval.fecs[index] += int(rate.fec > 0)
        else:
            for interval in self.intervals.values():
                interval.uas = [n + 1 for n in interval.uas]

        # At the end of an interval its counters start again from zero (7.2).
        for name, interval in self.intervals.items():
            interval.elapsed += 1
            if interval.elapsed == interval.length:
                self.intervals[name] = _Interval(interval.length)

    def _count(self, direction: str, crc: int, fec: int) -> None:
        if crc < 0 or fec < 0:
            raise ValueError("error counts must not be negative")
        counters = [self.totals[direction], self.current[direction]]
        counters += [i.errors[direction] for i in self.intervals.values()]
        for c in counters:
            c.crc += crc
            c.fec += fec

    # Memory

    def _write_all(self) -> None:
        d = self.device
        showtime = self.state == LineState.SHOWTIME
        d.set("xdslTerminal", terminal_word(d.role, self.state))
        d.set("ModemStatus", MODEM_STATUS_SHOWTIME if showtime else MODEM_STATUS_OTHER)
        if d.layout is None:
            # Firmware with an unknown layout: only the registers at fixed addresses.
            return
        reason_reg = ("xdsl2MetanoiaRtFailureReasons" if d.role == Role.RT
                      else "xdsl2MetanoiaOtFailureReasons")
        d.set(reason_reg, self.failure_reason)
        self._write_status(self.status if showtime else None)
        self._write_counters()

    def _write_status(self, s: LineStatus | None) -> None:
        d = self.device
        d.set("xdsl2LineStatusXtuTransSys", s.trans_sys if s else 0)
        d.set("xdsl2LineStatusActProfile", 1 << PROFILES.index(s.profile) if s else 0)
        d.set("xdsl2LineStatusInitResult", 0)
        d.set("xdsl2LineStatusElectricalLength", _db(s.electrical_length if s else None))
        d.set("nO_DsCombinationTpsTc", s.tps_tc if s else 0)
        d.set("nO_UsCombinationTpsTc", s.tps_tc if s else 0)

        for name, direction, channel, total_band, first_band in (
            ("Ds", s.downstream if s else None, 2, 10, 5),
            ("Us", s.upstream if s else None, 0, 9, 0),
        ):
            self._write_direction(name, direction, channel, total_band, first_band)

        if s:
            d.set("xdslTwConfig3", TWCONFIG3_ASCII_VERSION)
            d.set("xdsl2LInvG994VendorId0", words.octets(s.peer_vendor_id, 3))
            d.set("xdsl2LInvG994VendorId1", words.octets(s.own_vendor_id, 3))
            d.set("xdsl2LInvVersionNumber0", words.octets(s.peer_version.encode(), 6))
            d.set("xdsl2LInvVersionNumber1", words.octets(s.own_version.encode(), 6))

    def _write_direction(self, name: str, v: Direction | None, channel: int,
                         total_band: int, first_band: int) -> None:
        d = self.device
        d.set(f"xdsl2LineStatusAttainableRate{name}", v.attainable_rate if v else 0)
        d.set(f"xdsl2LineStatusActAtp{name}",
              words.scaled(v.transmit_power, 0.1, is_signed=True) if v else words.NOT_APPLICABLE)
        d.set(f"xdsl2LineStatusTrellis{name}", (TRUE if v.trellis else FALSE) if v else 0)
        d.set(f"xdsl2LineStatusActSnrMode{name}",
              (SNR_MODE_ENABLED if v.virtual_noise else SNR_MODE_DISABLED) if v else 0)

        d.set(f"xdsl2ChStatusActDataRate{channel}", v.data_rate if v else 0)
        d.set(f"xdsl2ChStatusPrevDataRate{channel}", 0)
        d.set(f"xdsl2ChStatusActDelay{channel}", v.delay if v else 0)
        d.set(f"xdsl2ChStatusActInp{channel}", words.scaled(v.inp, 0.1) if v else 0)
        d.set(f"xdsl2ChStatusIntlvDepth{channel}", v.interleave_depth if v else 0)
        d.set(f"xdsl2ChStatusIntlvBlock{channel}", v.interleave_block if v else 0)

        bands = v.bands if v else []
        count = 4 if name == "Ds" else 5
        for i in range(count):
            band = bands[i] if i < len(bands) else None
            self._write_band(first_band + i, band)
        self._write_band(total_band, v.total if v else None)

        prefix = "VisibleDsPb" if name == "Ds" else "VisibleUsPb"
        tones = v.tones if v else []
        for i in range(count):
            first, last = tones[i] if i < len(tones) else (0, 0)
            d.set(f"{prefix}{i}FirstTone", first)
            d.set(f"{prefix}{i}LastTone", last)

    def _write_band(self, index: int, band: Band | None) -> None:
        band = band or Band()
        d = self.device
        d.set(f"xdsl2LineBandStatusLnAtten{index}", _db(band.line_attenuation))
        d.set(f"xdsl2LineBandStatusSigAtten{index}", _db(band.signal_attenuation))
        d.set(f"xdsl2LineBandStatusSnrMargin{index}", _db(band.snr_margin, is_signed=True))

    def _write_counters(self) -> None:
        d = self.device
        d.set("xdslMetanoiaShowtimeSeconds", words.counter(self.showtime_seconds))
        for direction, index in (("ds", 0), ("us", 1)):
            for prefix, counters in (("", self.totals), ("Curr", self.current)):
                c = counters[direction]
                d.set(f"xdslMetanoiaRt{prefix}CodingViolations{index}", words.counter(c.crc))
                d.set(f"xdslMetanoiaRt{prefix}CorrectedBlocks{index}", words.counter(c.fec))

        for name, interval in self.intervals.items():
            for index in (0, 1):
                d.set(f"xdsl2PMLCurr{name}TimeElapsed{index}", interval.elapsed)
                d.set(f"xdsl2PMLCurr{name}Fecs{index}", words.counter(interval.fecs[index]))
                d.set(f"xdsl2PMLCurr{name}Es{index}", words.counter(interval.es[index]))
                d.set(f"xdsl2PMLCurr{name}Ses{index}", 0)
                d.set(f"xdsl2PMLCurr{name}Loss{index}", 0)
                d.set(f"xdsl2PMLCurr{name}Uas{index}", words.counter(interval.uas[index]))
                d.set(f"xdsl2PMLInitCurr{name}TimeElapsed{index}", interval.elapsed)
                d.set(f"xdsl2PMLInitCurr{name}FullInits{index}",
                      words.counter(interval.full_inits))
            for direction, channel in (("us", 0), ("ds", 2)):
                c = interval.errors[direction]
                d.set(f"xdsl2PMChCurr{name}TimeElapsed{channel}", interval.elapsed)
                d.set(f"xdsl2PMChCurr{name}CodingViolations{channel}", words.counter(c.crc))
                d.set(f"xdsl2PMChCurr{name}CorrectedBlocks{channel}", words.counter(c.fec))


def _db(value: float | None, *, is_signed: bool = False) -> int:
    """Encodes a value in 0.1 dB; None is 'not applicable' (7.3)."""
    if value is None:
        return words.NOT_APPLICABLE
    return words.scaled(value, 0.1, is_signed=is_signed)
