"""Tests of src/mt5311d/layout.uc, partly with the simulated device."""

import pytest

from mt5311sim.device import (
    FIRMWARE_750202,
    FIRMWARE_BRANCH_161,
    FIRMWARE_UNKNOWN,
    Device,
    Firmware,
    Role,
)
from mt5311sim.registers import Layout
from ucode import UcodeError

ID_ADDRESSES = [0x006C31, 0x006C32, 0x006C33, 0x006C34, 0x006C35, 0x006C36]
CHECK_VALUES = [6, 8, 10, 1, 2, 1, 1]

# Table of the layout check in section 8.2.
CHECK_ADDRESSES = [
    0x006FEF, 0x006FF3, 0x006FF7, 0x006FFB, 0x006FFF, 0x007003, 0x007011,  # 1.60
    0x007004, 0x007008, 0x00700C, 0x007010, 0x007014, 0x007018, 0x007026,  # 1.61
]

ID_750202 = [0x750202, 0x090718, 0x173044, 0x801568, 0x000329, 0x474154]


@pytest.fixture
def select(ucode):
    """Parses the identification words and selects the layout."""

    def select(id_words, check_words):
        source = """
            import * as l from 'mt5311d.layout';
            printf('%J', l.select(l.parse_id(ID), CHECK));
        """
        return ucode.run(source, ID=id_words, CHECK=check_words)

    return select


def test_id_addresses(ucode):
    assert ucode.run("import * as l from 'mt5311d.layout'; printf('%J', l.ID_ADDRESSES);") \
        == ID_ADDRESSES


def test_check_addresses(ucode):
    assert ucode.call("mt5311d.layout", "check_addresses") == CHECK_ADDRESSES


def test_parse_id(ucode):
    assert ucode.call("mt5311d.layout", "parse_id", ID_750202) == {
        "version": 0x750202, "date": 0x090718, "time": 0x173044, "board_type": 0x801568,
        "terminal": 0x000329, "signature": 0x474154, "valid": True,
    }
    assert ucode.call("mt5311d.layout", "parse_id", [0] * 6)["valid"] is False


@pytest.mark.parametrize("words", [[0] * 5, [0] * 7, None])
def test_parse_id_needs_six_words(ucode, words):
    with pytest.raises(UcodeError, match="needs 6 words"):
        ucode.call("mt5311d.layout", "parse_id", words)


def test_select_needs_all_check_words(select):
    with pytest.raises(UcodeError, match="needs 14 words"):
        select(ID_750202, CHECK_VALUES)


@pytest.mark.parametrize(
    ("firmware", "layout", "reason"),
    [
        (FIRMWARE_750202, "1.60", "known build"),
        (FIRMWARE_BRANCH_161, "1.61", "layout check"),
        (FIRMWARE_UNKNOWN, None, "no layout passes the layout check"),
    ],
)
def test_select_with_simulated_device(select, firmware, layout, reason):
    device = Device(firmware)
    result = select([device.peek(a) for a in ID_ADDRESSES],
                    [device.peek(a) for a in CHECK_ADDRESSES])
    assert (result["layout"], result["reason"]) == (layout, reason)


def test_unknown_build_with_layout_160(select):
    # Another build of branch 1.60, e.g. 020818_163044 (8.1).
    device = Device(Firmware(0x750202, "020818", "163044", Layout.BRANCH_160))
    result = select([device.peek(a) for a in ID_ADDRESSES],
                    [device.peek(a) for a in CHECK_ADDRESSES])
    assert result == {"layout": "1.60", "passed": ["1.60"], "reason": "layout check"}


def test_ot_device_is_not_rejected_here(select):
    device = Device(role=Role.OT)
    result = select([device.peek(a) for a in ID_ADDRESSES],
                    [device.peek(a) for a in CHECK_ADDRESSES])
    assert result["layout"] == "1.60"


def test_invalid_signature(select):
    result = select(ID_750202[:5] + [0x000000], CHECK_VALUES + CHECK_VALUES)
    assert result == {"layout": None, "passed": [], "reason": "invalid signature"}


def test_known_build_failing_the_check_is_not_supported(select):
    words = [0] * 7 + CHECK_VALUES
    result = select(ID_750202, words)
    assert result == {"layout": None, "passed": ["1.61"],
                      "reason": "known build fails the layout check"}


def test_one_wrong_word_fails_a_layout(select):
    for i in range(7):
        words = CHECK_VALUES + [0] * 7
        words[i] += 1
        assert select(ID_750202, words)["layout"] is None, i


def test_several_layouts_passing_is_not_supported(select):
    unknown = [0x760101, 0x010124, 0x120000, 0x801568, 0x000329, 0x474154]
    result = select(unknown, CHECK_VALUES + CHECK_VALUES)
    assert result == {"layout": None, "passed": ["1.60", "1.61"],
                      "reason": "several layouts pass the layout check"}
