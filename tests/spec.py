"""Reads the register tables of Appendix A from the specification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

from ucode import REPO

SPEC = REPO / "MT5311_EBM_Monitoring_Spec.md"

# | `Symbol` | Addr 1.60 | Addr 1.61 | Words | Class | ...; Addr 1.61 may be "=".
_ROW = re.compile(r"^\| `(\w+)` \| `([0-9A-F]{6})` \| (?:`([0-9A-F]{6})`|(=)) \| (\d+) \|")


@dataclass(frozen=True)
class SpecRegister:
    name: str
    addr_160: int
    addr_161: int
    words: int


@cache
def registers() -> dict[str, SpecRegister]:
    rows = {}
    for line in SPEC.read_text().splitlines():
        if m := _ROW.match(line):
            addr_160 = int(m[2], 16)
            addr_161 = addr_160 if m[4] else int(m[3], 16)
            rows[m[1]] = SpecRegister(m[1], addr_160, addr_161, int(m[5]))
    if not rows:
        raise ValueError(f"no register rows found in {SPEC}")
    return rows
