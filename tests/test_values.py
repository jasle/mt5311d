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
        "ModemStatus": [0x00000F],
        "xdslTerminal": [0x000329],
    }) == {
        "xdsl2LineBandStatusSnrMargin10": 3.3,
        "xdsl2LineStatusActAtpUs": -2.9,
        "xdsl2LineBandStatusSigAtten10": None,
        "xdslMetanoiaRtCurrCodingViolations0": 0x7FFFFF,
        "ModemStatus": 0x00000F,
        "xdslTerminal": {"role": "RT", "chip": "AURORA", "line_state": "showtime",
                         "showtime": True},
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


# Identification and enumerations (9.2 to 9.4)


def test_firmware_750202(values):
    assert values("firmware", {"version": 0x750202, "date": 0x090718, "time": 0x173044}) == {
        "version": 0x750202, "major": 0x75, "minor": 0x0202,
        "date": "2018-09-07", "time": "17:30:44",
    }


def test_firmware_with_invalid_bcd(values):
    result = values("firmware", {"version": 0, "date": 0x0907A8, "time": 0xFFFFFF})
    assert (result["date"], result["time"]) == (None, None)


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        # Examples observed in section 9.2.1.
        (0x000029, {"role": "RT", "chip": "AURORA", "line_state": "idle", "showtime": False}),
        (0x000329, {"role": "RT", "chip": "AURORA", "line_state": "showtime", "showtime": True}),
        (0x000128, {"role": "OT", "chip": "AURORA", "line_state": "handshake", "showtime": False}),
        (0x000221, {"role": "RT", "chip": "ARGO", "line_state": "training", "showtime": False}),
        (0x000049, {"role": "RT", "chip": "BARTON", "line_state": "idle", "showtime": False}),
        (0x000041, {"role": "RT", "chip": "BORA", "line_state": "idle", "showtime": False}),
    ],
)
def test_terminal(values, word, expected):
    assert values("terminal", word) == expected


@pytest.mark.parametrize(
    ("word", "name"),
    [(0, "none"), (1, "loss_of_signal"), (2, "loss_of_power"), (3, "crc_errors"),
     (4, "training_failure"), (5, "disconnect"), (6, "snr_below_minimum"), (7, None)],
)
def test_failure_reason(values, word, name):
    assert values("failure_reason", word) == {"value": word, "name": name}


@pytest.mark.parametrize(
    ("word", "name", "standard", "annex", "family"),
    [
        # Values used by this device class (9.3.2); names from RFC 5650.
        (18, "g9923PotsNonOverlapped", "G.992.3", "A", "ADSL2"),
        (20, "g9923IsdnNonOverlapped", "G.992.3", "B", "ADSL2"),
        (40, "g9925PotsNonOverlapped", "G.992.5", "A", "ADSL2+"),
        (42, "g9925IsdnNonOverlapped", "G.992.5", "B", "ADSL2+"),
        (56, "g9932AnnexA", "G.993.2", "A", "VDSL2"),
        (57, "g9932AnnexB", "G.993.2", "B", "VDSL2"),
        # Other bits of the full list.
        (0, "ansit1413", "ANSI T1.413", None, "ADSL"),
        (6, "g9921tcmIsdnNonOverlapped", "G.992.1", "C", "ADSL"),
        (30, "g9923AnnexJAllDigNonOverlapped", "G.992.3", "J", "ADSL2"),
        (58, "g9932AnnexC", "G.993.2", "C", "VDSL2"),
        (13, None, None, None, None),
        (64, None, None, None, None),
    ],
)
def test_trans_sys(values, word, name, standard, annex, family):
    assert values("trans_sys", word) == {"value": word, "name": name, "standard": standard,
                                         "annex": annex, "family": family}


@pytest.mark.parametrize(
    ("word", "name"),
    [(0x01, "8a"), (0x02, "8b"), (0x04, "8c"), (0x08, "8d"), (0x10, "12a"), (0x20, "12b"),
     (0x40, "17a"), (0x80, "30a"), (0x00, None), (0x41, None), (0x100, None)],
)
def test_profile(values, word, name):
    assert values("profile", word) == {"value": word, "name": name}


@pytest.mark.parametrize(
    ("word", "name"), [(0x20, "PTM"), (0x40, "ATM"), (0x80, "STM"), (0x00, None)],
)
def test_tps_tc(values, word, name):
    assert values("tps_tc", word) == {"value": word, "name": name}


@pytest.mark.parametrize(("word", "value"), [(1, True), (2, False), (0, None), (3, None)])
def test_truth(values, word, value):
    assert values("truth", word) is value


@pytest.mark.parametrize(("word", "name"), [(1, "disabled"), (2, "enabled"), (0, None)])
def test_snr_mode(values, word, name):
    assert values("snr_mode", word) == {"value": word, "name": name}


@pytest.mark.parametrize(
    ("word", "name"),
    [(0, "noFail"), (1, "configError"), (2, "configNotFeasible"), (3, "commFail"),
     (4, "noPeerAtu"), (5, "otherCause"), (6, None)],
)
def test_init_result(values, word, name):
    assert values("init_result", word) == {"value": word, "name": name}


def test_enumerations_of_the_simulated_line(decode_all):
    modem = Modem()
    modem.line.status.upstream.trellis = False
    modem.line.status.downstream.virtual_noise = True
    modem.line.showtime()
    result = decode_all(raw_words(modem, [
        "xdslTerminal", "xdsl2LineStatusXtuTransSys", "xdsl2LineStatusActProfile",
        "nO_DsCombinationTpsTc", "xdsl2LineStatusTrellisDs", "xdsl2LineStatusTrellisUs",
        "xdsl2LineStatusActSnrModeDs", "xdsl2LineStatusActSnrModeUs",
        "xdsl2LineStatusInitResult",
    ]))
    assert result["xdslTerminal"]["line_state"] == "showtime"
    assert result["xdsl2LineStatusXtuTransSys"]["name"] == "g9932AnnexB"
    assert result["xdsl2LineStatusActProfile"]["name"] == modem.line.status.profile
    assert result["nO_DsCombinationTpsTc"]["name"] == "PTM"
    assert (result["xdsl2LineStatusTrellisDs"], result["xdsl2LineStatusTrellisUs"]) == (True, False)
    assert result["xdsl2LineStatusActSnrModeDs"]["name"] == "enabled"
    assert result["xdsl2LineStatusActSnrModeUs"]["name"] == "disabled"
    assert result["xdsl2LineStatusInitResult"]["name"] == "noFail"


def test_failure_reason_of_the_simulated_line(decode_all):
    modem = Modem()
    modem.line.showtime()
    modem.line.retrain(FailureReason.CRC_ERRORS)
    assert decode_all(raw_words(modem, ["xdsl2MetanoiaRtFailureReasons"])) == {
        "xdsl2MetanoiaRtFailureReasons": {"value": 3, "name": "crc_errors"},
    }
