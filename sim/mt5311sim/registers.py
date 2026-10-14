"""Registers of the simulated DSP memory (spec Appendix A).

Only the registers that mt5311d uses are listed. Addresses are in space X and are
given for both known address layouts (8.1). Families of registers with a regular
structure are generated from the address of their first instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Layout(Enum):
    BRANCH_160 = "1.60"
    BRANCH_161 = "1.61"


@dataclass(frozen=True)
class Register:
    name: str
    addr_160: int
    addr_161: int
    words: int = 1

    def address(self, layout: Layout) -> int:
        return self.addr_160 if layout is Layout.BRANCH_160 else self.addr_161


REGISTERS: dict[str, Register] = {}


def register(name: str) -> Register:
    return REGISTERS[name]


def _add(name: str, addr_160: int, addr_161: int, words: int = 1) -> None:
    if name in REGISTERS:
        raise ValueError(f"register {name} defined twice")
    REGISTERS[name] = Register(name, addr_160, addr_161, words)


def _define() -> None:
    # Identification and system (A.1, 8.2)
    for name, addr in [
        ("ModemStatus", 0x00001D),
        ("xdslFirmwareVer", 0x006C31),
        ("xdslFirmwareDate", 0x006C32),
        ("xdslFirmwareTime", 0x006C33),
        ("xdslBoardType", 0x006C34),
        ("xdslTerminal", 0x006C35),
        ("xdslMetanoiaSignature", 0x006C36),
        ("xdslMetanoiaShowtimeSeconds", 0x006D35),
    ]:
        _add(name, addr, addr)

    _add("xdslTwConfig3", 0x006E6F, 0x006E87)

    # Line status (A.2)
    _add("nO_DsCombinationTpsTc", 0x001778, 0x001775)
    _add("nO_UsCombinationTpsTc", 0x001779, 0x001776)
    _add("xdsl2LineStatusXtuTransSys", 0x006F19, 0x006F2E)
    _add("xdsl2LineStatusInitResult", 0x006F1B, 0x006F30)
    _add("xdsl2LineStatusAttainableRateDs", 0x006F20, 0x006F35)
    _add("xdsl2LineStatusAttainableRateUs", 0x006F21, 0x006F36)
    _add("xdsl2LineStatusActAtpDs", 0x006F24, 0x006F39)
    _add("xdsl2LineStatusActAtpUs", 0x006F25, 0x006F3A)
    _add("xdsl2LineStatusActProfile", 0x006F26, 0x006F3B)
    _add("xdsl2LineStatusActSnrModeDs", 0x006F2D, 0x006F42)
    _add("xdsl2LineStatusActSnrModeUs", 0x006F2E, 0x006F43)
    _add("xdsl2LineStatusElectricalLength", 0x006F2F, 0x006F44)
    _add("xdsl2LineStatusTrellisDs", 0x006FD2, 0x006FE7)
    _add("xdsl2LineStatusTrellisUs", 0x006FD3, 0x006FE8)

    # Band table, 4 words per band (8.2, 9.1): xdsl2LineBand<i>, LnAtten, SigAtten, SnrMargin
    for i in range(11):
        for offset, field in enumerate(["xdsl2LineBand", "xdsl2LineBandStatusLnAtten",
                                        "xdsl2LineBandStatusSigAtten",
                                        "xdsl2LineBandStatusSnrMargin"]):
            _add(f"{field}{i}", 0x006FD7 + 4 * i + offset, 0x006FEC + 4 * i + offset)

    _add("xdsl2MetanoiaOtFailureReasons", 0x007F1C, 0x007F31)
    _add("xdsl2MetanoiaRtFailureReasons", 0x007F59, 0x007F6E)

    for i in range(5):
        _add(f"VisibleUsPb{i}FirstTone", 0x006E37 + 2 * i, 0x006E4F + 2 * i)
        _add(f"VisibleUsPb{i}LastTone", 0x006E38 + 2 * i, 0x006E50 + 2 * i)
    for i in range(4):
        _add(f"VisibleDsPb{i}FirstTone", 0x006E47 + 2 * i, 0x006E5F + 2 * i)
        _add(f"VisibleDsPb{i}LastTone", 0x006E48 + 2 * i, 0x006E60 + 2 * i)

    # Channel status (A.3), 14 words per channel. Channels 1 and 3 are unused (9.1);
    # only their Unit word is needed for the layout check.
    for i in range(4):
        _add(f"xdsl2ChStatusUnit{i}", 0x007003 + 14 * i, 0x007018 + 14 * i)
    for i in (0, 2):
        for offset, field in [(1, "ActDataRate"), (2, "PrevDataRate"), (3, "ActDelay"),
                              (4, "ActInp"), (9, "IntlvDepth"), (10, "IntlvBlock")]:
            _add(f"xdsl2ChStatus{field}{i}", 0x007003 + 14 * i + offset,
                 0x007018 + 14 * i + offset)

    # Inventory (A.4)
    _add("xdsl2LInvG994VendorId0", 0x0079C8, 0x0079DD, 3)
    _add("xdsl2LInvVersionNumber0", 0x0079CE, 0x0079E3, 6)
    _add("xdsl2LInvG994VendorId1", 0x0079E4, 0x0079F9, 3)
    _add("xdsl2LInvVersionNumber1", 0x0079EA, 0x0079FF, 6)

    # Performance monitoring (A.5). Per index: 15-minute block, then 1-day block.
    pml_fields = ["TimeElapsed", "Fecs", "Es", "Ses", "Loss", "Uas"]
    for i in range(2):
        for interval, start in [("15M", 0), ("1Day", 8)]:
            for offset, field in enumerate(pml_fields):
                base = 17 * i + start + offset
                _add(f"xdsl2PMLCurr{interval}{field}{i}", 0x007C1F + base, 0x007C34 + base)

    for i in range(2):
        for interval, start in [("15M", 0), ("1Day", 7)]:
            for offset, field in enumerate(["TimeElapsed", "FullInits"]):
                base = 14 * i + start + offset
                _add(f"xdsl2PMLInitCurr{interval}{field}{i}", 0x007C40 + base,
                     0x007C55 + base)

    for i in (0, 2):
        for interval, start in [("15M", 0), ("1Day", 5)]:
            for offset, field in enumerate(["TimeElapsed", "CodingViolations",
                                            "CorrectedBlocks"]):
                base = 11 * i + start + offset
                _add(f"xdsl2PMChCurr{interval}{field}{i}", 0x007C9D + base, 0x007CB2 + base)

    # Vendor counter table of the xTU-R (9.1). Per index: blocks of 10 words for the
    # totals, Curr and LastSec; only CorrectedBlocks and CodingViolations are needed.
    for i in range(2):
        for prefix, start in [("", 0), ("Curr", 10)]:
            for offset, field in enumerate(["CorrectedBlocks", "CodingViolations"]):
                base = 30 * i + start + offset
                _add(f"xdslMetanoiaRt{prefix}{field}{i}", 0x007F1D + base, 0x007F32 + base)


_define()
