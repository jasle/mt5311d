import re
from pathlib import Path

import pytest

from mt5311sim.registers import REGISTERS, Layout, register

SPEC = Path(__file__).parents[2] / "MT5311_EBM_Monitoring_Spec.md"

# Rows of the Appendix A tables: | `Symbol` | Addr 1.60 | Addr 1.61 | Words | ...
ROW = re.compile(r"^\| `(\w+)` \| `([0-9A-F]{6})` \| (?:`([0-9A-F]{6})`|(=)) \| (\d+) \|")


def spec_registers() -> dict[str, tuple[int, int, int]]:
    rows = {}
    for line in SPEC.read_text().splitlines():
        if m := ROW.match(line):
            addr_160 = int(m[2], 16)
            addr_161 = addr_160 if m[4] else int(m[3], 16)
            rows[m[1]] = (addr_160, addr_161, int(m[5]))
    return rows


def test_registers_match_the_specification():
    spec = spec_registers()
    assert spec, "no rows found in Appendix A"
    for reg in REGISTERS.values():
        assert reg.name in spec, f"{reg.name} is not in Appendix A"
        assert (reg.addr_160, reg.addr_161, reg.words) == spec[reg.name], reg.name


@pytest.mark.parametrize("layout", list(Layout))
def test_registers_do_not_overlap(layout):
    regs = sorted(REGISTERS.values(), key=lambda r: r.address(layout))
    for a, b in zip(regs, regs[1:]):
        assert a.address(layout) + a.words <= b.address(layout), (a.name, b.name)


@pytest.mark.parametrize(
    ("name", "addr_160", "addr_161"),
    [
        ("xdsl2LineBand6", 0x006FEF, 0x007004),
        ("xdsl2LineBand7", 0x006FF3, 0x007008),
        ("xdsl2LineBand8", 0x006FF7, 0x00700C),
        ("xdsl2LineBand9", 0x006FFB, 0x007010),
        ("xdsl2LineBand10", 0x006FFF, 0x007014),
        ("xdsl2ChStatusUnit0", 0x007003, 0x007018),
        ("xdsl2ChStatusUnit1", 0x007011, 0x007026),
    ],
)
def test_layout_check_addresses(name, addr_160, addr_161):
    # Table of the layout check in section 8.2.
    assert register(name).address(Layout.BRANCH_160) == addr_160
    assert register(name).address(Layout.BRANCH_161) == addr_161
