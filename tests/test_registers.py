"""Tests of src/mt5311d/registers.uc against the specification and the simulator."""

import pytest

import spec
from mt5311sim import registers as sim
from ucode import UcodeError

LAYOUTS = {"1.60": sim.Layout.BRANCH_160, "1.61": sim.Layout.BRANCH_161}


@pytest.fixture(scope="module")
def table(ucode):
    """All registers of the module: name -> {"1.60": addr, "1.61": addr, "words": n}."""
    source = """
        import * as r from 'mt5311d.registers';
        const table = {};
        for (let name in r.names())
            table[name] = {
                [r.LAYOUT_160]: r.address(r.LAYOUT_160, name),
                [r.LAYOUT_161]: r.address(r.LAYOUT_161, name),
                words: r.words(name),
            };
        printf('%J', table);
    """
    return ucode.run(source)


def test_table_is_not_empty(table):
    assert "xdslFirmwareVer" in table


def test_registers_match_the_specification(table):
    rows = spec.registers()
    for name, reg in table.items():
        assert name in rows, f"{name} is not in Appendix A"
        row = rows[name]
        assert (reg["1.60"], reg["1.61"], reg["words"]) == \
            (row.addr_160, row.addr_161, row.words), name


def test_registers_match_the_simulator(table):
    shared = [name for name in table if name in sim.REGISTERS]
    assert shared
    for name in shared:
        for layout, sim_layout in LAYOUTS.items():
            assert table[name][layout] == sim.register(name).address(sim_layout), name


@pytest.mark.parametrize("layout", LAYOUTS)
def test_registers_do_not_overlap(table, layout):
    regs = sorted(table.items(), key=lambda item: item[1][layout])
    for (name_a, a), (name_b, b) in zip(regs, regs[1:]):
        assert a[layout] + a["words"] <= b[layout], (name_a, name_b)


def test_unknown_register(ucode):
    with pytest.raises(UcodeError, match="unknown register xdslNope"):
        ucode.call("mt5311d.registers", "address", "1.60", "xdslNope")
    with pytest.raises(UcodeError, match="unknown register xdslNope"):
        ucode.call("mt5311d.registers", "words", "xdslNope")


def test_unknown_layout(ucode):
    with pytest.raises(UcodeError, match="unknown layout 1.62"):
        ucode.call("mt5311d.registers", "address", "1.62", "xdslFirmwareVer")
