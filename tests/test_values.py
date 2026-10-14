"""Tests of src/mt5311d/values.uc against the specification and the simulator."""

import pytest

import spec
from mt5311sim.line import FailureReason
from mt5311sim.modem import Modem
from ucode import UcodeError

VALUES = "import * as v from 'mt5311d.values';\n"


@pytest.fixture
def values(ucode):
    """Calls a function of the module."""

    def call(function, *args):
        return ucode.call("mt5311d.values", function, *args)

    return call


@pytest.fixture
def decode_all(ucode):
    """Decodes several registers at once: {name: words} -> {name: value}."""

    def decode_all(raw):
        source = VALUES + """
            const result = {};
            for (let name, words in RAW)
                result[name] = v.decode(name, words);
            printf('%J', result);
        """
        return ucode.run(source, RAW=raw)

    return decode_all


# Format table


@pytest.fixture(scope="module")
def formats(ucode):
    source = """
        import * as r from 'mt5311d.registers';
        import * as v from 'mt5311d.values';
        printf('%J', { registers: r.names(), formats: map(v.names(), (n) => [ n, v.format(n) ]) });
    """
    result = ucode.run(source)
    return result["registers"], dict(result["formats"])


def test_every_register_has_a_format(formats):
    register_names, table = formats
    assert sorted(table) == register_names


def test_formats_match_the_specification(formats):
    _, table = formats
    rows = spec.registers()
    for name, fmt in table.items():
        row = rows[name]
        assert fmt["class"] == row.value_class, name
        if fmt["class"] != "M":
            continue
        assert fmt["signed"] == row.type_unit.startswith("Integer32"), name
        assert fmt["div"] == (10 if "0.1" in row.type_unit else 1), name
        assert fmt["unit"] in row.type_unit, name


def test_unknown_register(values):
    with pytest.raises(UcodeError, match="no format for register xdslNope"):
        values("decode", "xdslNope", [0])


# Number formats (7.2)


@pytest.mark.parametrize(
    ("word", "value"),
    [(0x000000, 0), (0x000021, 33), (0x7FFFFF, 0x7FFFFF), (0x800000, -0x800000),
     (0xFFFFE3, -29), (0xFFFFFF, -1)],
)
def test_signed24(values, word, value):
    assert values("signed24", word) == value


@pytest.mark.parametrize("word", [0x7FFFFF, 0x7FFFFE, 0xC69A53, 0x19979F])
def test_special_values(values, word):
    assert values("is_special", word, False) is True
    assert values("is_special", word, True) is True


def test_ffffcc_is_only_special_for_unsigned_registers(values):
    assert values("is_special", 0xFFFFCC, False) is True
    assert values("is_special", 0xFFFFCC, True) is False
    signed_db = {"signed": True, "div": 10}
    assert values("measurement", 0xFFFFCC, signed_db) == -5.2
    assert values("measurement", 0xFFFFCC, {"signed": False, "div": 10}) is None


@pytest.mark.parametrize(
    ("word", "fmt", "value"),
    [
        (0x000021, {"signed": True, "div": 10}, 3.3),
        (0xFFFFE3, {"signed": True, "div": 10}, -2.9),
        (0x0000FB, {"signed": False, "div": 10}, 25.1),
        (0x000000, {"signed": False, "div": 10}, 0.0),
        (100000, {"signed": False, "div": 1}, 100000),
        (0x7FFFFE, {"signed": False, "div": 10}, None),
        (0x7FFFFF, {"signed": True, "div": 1}, None),
    ],
)
def test_measurement(values, word, fmt, value):
    result = values("measurement", word, fmt)
    assert result == value
    assert type(result) is type(value)


@pytest.mark.parametrize(
    ("previous", "current", "delta"),
    [(0, 0, 0), (10, 15, 5), (0xFFFFFE, 0x000003, 5), (0xFFFFFF, 0x000000, 1), (5, 4, 0xFFFFFF)],
)
def test_counter_delta(values, previous, current, delta):
    assert values("counter_delta", previous, current) == delta


def test_combine48(values):
    assert values("combine48", 0x000001, 0x000002) == (1 << 24) + 2
    assert values("combine48", 0xFFFFFF, 0xFFFFFF) == (1 << 48) - 1


def test_decode_by_class(decode_all):
    assert decode_all({
        "xdsl2LineBandStatusSnrMargin10": [0x000021],
        "xdsl2LineStatusActAtpUs": [0xFFFFE3],
        "xdsl2LineBandStatusSigAtten10": [0x7FFFFE],
        "xdslMetanoiaRtCurrCodingViolations0": [0x7FFFFF],
        "xdslTerminal": [0x000329],
    }) == {
        "xdsl2LineBandStatusSnrMargin10": 3.3,
        "xdsl2LineStatusActAtpUs": -2.9,
        "xdsl2LineBandStatusSigAtten10": None,
        "xdslMetanoiaRtCurrCodingViolations0": 0x7FFFFF,
        "xdslTerminal": 0x000329,
    }


# Cross-check with the simulator's line model


def raw_words(modem, names):
    return {name: modem.device.get(name) for name in names}


def test_measurements_of_the_simulated_line(decode_all):
    modem = Modem()
    modem.line.showtime()
    ds, us = modem.line.status.downstream, modem.line.status.upstream

    expected = {
        "xdsl2ChStatusActDataRate2": ds.data_rate,
        "xdsl2ChStatusActDataRate0": us.data_rate,
        "xdsl2LineStatusAttainableRateDs": ds.attainable_rate,
        "xdsl2LineStatusAttainableRateUs": us.attainable_rate,
        "xdsl2LineStatusActAtpDs": ds.transmit_power,
        "xdsl2LineStatusActAtpUs": us.transmit_power,
        "xdsl2ChStatusActDelay2": ds.delay,
        "xdsl2ChStatusActDelay0": us.delay,
        "xdsl2ChStatusActInp2": ds.inp,
        "xdsl2ChStatusActInp0": us.inp,
        "xdsl2LineBandStatusSnrMargin10": ds.total.snr_margin,
        "xdsl2LineBandStatusSigAtten10": ds.total.signal_attenuation,
        "xdsl2LineBandStatusLnAtten10": ds.total.line_attenuation,
        "xdsl2LineBandStatusSnrMargin9": us.total.snr_margin,
    }
    for i, band in enumerate(us.bands):
        expected[f"xdsl2LineBandStatusLnAtten{i}"] = band and band.line_attenuation
        expected[f"xdsl2LineBandStatusSigAtten{i}"] = band and band.signal_attenuation

    assert decode_all(raw_words(modem, expected)) == expected


def test_measurements_outside_showtime(decode_all):
    modem = Modem()
    modem.line.showtime()
    modem.line.retrain(FailureReason.LOSS_OF_SIGNAL)
    names = ["xdsl2LineStatusActAtpDs", "xdsl2LineBandStatusSnrMargin10",
             "xdsl2LineBandStatusSigAtten10", "xdsl2LineBandStatusLnAtten1"]
    assert decode_all(raw_words(modem, names)) == dict.fromkeys(names)


def test_counters_of_the_simulated_line(decode_all):
    modem = Modem()
    modem.line.showtime()
    modem.line.add_errors("ds", crc=0x1000003, fec=7)
    modem.line.tick(42)
    assert decode_all(raw_words(modem, [
        "xdslMetanoiaRtCurrCodingViolations0", "xdslMetanoiaRtCurrCorrectedBlocks0",
        "xdslMetanoiaShowtimeSeconds",
    ])) == {
        "xdslMetanoiaRtCurrCodingViolations0": 3,
        "xdslMetanoiaRtCurrCorrectedBlocks0": 7,
        "xdslMetanoiaShowtimeSeconds": 42,
    }
