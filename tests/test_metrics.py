"""Tests of src/mt5311d/metrics.uc: the reply of `ubus call dsl metrics`."""

import pytest

from mt5311sim.device import FIRMWARE_UNKNOWN, LineState
from mt5311sim.line import FailureReason

METRICS = {
    "imports": "import * as m from 'mt5311d.metrics';",
    "report": "m.metrics(state, { version: '1.0' })",
}

# Fields of the Lantiq daemon (dsl_cpe_ubus.c in OpenWrt 25.12) and their types.
U32, DOUBLE, BOOL, STR, BYTES = int, float, bool, str, list
DIRECTION = {
    "vector": BOOL, "trellis": BOOL, "bitswap": BOOL, "retx": BOOL, "virtual_noise": BOOL,
    "ra_mode": STR, "ra_mode_num": U32, "interleave_delay": U32, "inp": DOUBLE,
    "data_rate": U32, "latn": DOUBLE, "satn": DOUBLE, "snr": DOUBLE, "actps": DOUBLE,
    "actatp": DOUBLE, "attndr": U32, "mineftr": U32,
}
ERRORS = dict.fromkeys(
    ["es", "ses", "loss", "uas", "lofs", "fecs", "leftrs", "cv_c", "fec_c", "hec", "ibe",
     "crc_p", "crcp_p", "cv_p", "cvp_p", "rx_corrupted", "rx_uncorrected_protected",
     "rx_retransmitted", "rx_corrected", "tx_retransmitted"], U32)
LANTIQ_SCHEMA = {
    "api_version": STR, "firmware_version": STR, "chipset": STR, "driver_version": STR,
    "state": STR, "state_num": U32, "up": BOOL, "uptime": U32,
    "atu_c": {"vendor_id": BYTES, "vendor": STR, "system_vendor_id": BYTES,
              "system_vendor": STR, "version": BYTES, "serial": BYTES},
    "power_state": STR, "power_state_num": U32, "xtse": BYTES, "annex": STR,
    "standard": STR, "profile": STR, "mode": STR,
    "upstream": DIRECTION, "downstream": DIRECTION,
    "errors": {"near": ERRORS, "far": ERRORS},
}


def check_schema(value, schema, path="metrics"):
    for key, item in value.items():
        assert key in schema, f"{path}.{key} is not a field of the Lantiq daemon"
        expected = schema[key]
        if isinstance(expected, dict):
            assert isinstance(item, dict), f"{path}.{key}"
            check_schema(item, expected, f"{path}.{key}")
        else:
            assert type(item) is expected, f"{path}.{key}: {type(item)} is not {expected}"


def test_showtime(run_poller, simulator):
    line = simulator.modem.line
    line.showtime()
    line.tick(42)
    line.add_errors("ds", crc=3, fec=1234)
    line.add_errors("us", crc=1, fec=5)

    (metrics,) = run_poller(["refresh"], **METRICS)
    check_schema(metrics, LANTIQ_SCHEMA)
    ds, us = line.status.downstream, line.status.upstream

    assert metrics == {
        "chipset": "Metanoia MT5311",
        "driver_version": "mt5311d 1.0",
        "firmware_version": "750202 (2018-09-07 17:30:44)",
        "state": "Showtime with TC-Layer sync",
        "state_num": 7,
        "up": True,
        "uptime": 42,
        "atu_c": {
            "vendor_id": list(line.status.peer_vendor_id),
            "vendor": "Broadcom 28.192",
            "version": list(line.status.peer_version.encode()),
        },
        "standard": "G.993.2",
        "annex": "B",
        "profile": "17a",
        "mode": "G.993.2 (VDSL2, Profile 17a)",
        "downstream": {
            "trellis": True, "virtual_noise": False, "interleave_delay": 0, "inp": 0.0,
            "data_rate": ds.data_rate * 1000, "latn": 25.9, "satn": 25.1, "snr": 3.3,
            "actatp": 12.8, "attndr": ds.attainable_rate * 1000,
        },
        "upstream": {
            "trellis": True, "virtual_noise": False, "interleave_delay": 0, "inp": 0.0,
            "data_rate": us.data_rate * 1000, "snr": 6.0, "actatp": -2.9,
            "attndr": us.attainable_rate * 1000,
        },
        "errors": {
            # No "loss": xdslMetanoiaRtLoss0 is not plausible on a device.
            "near": {"cv_c": 3, "fec_c": 1234, "fecs": 0, "es": 0, "ses": 0, "uas": 0},
            "far": {"cv_c": 1, "fec_c": 5},
        },
    }


def test_units(run_poller, simulator):
    line = simulator.modem.line
    line.status.downstream.delay = 8
    line.status.downstream.inp = 4.5
    line.showtime()
    (metrics,) = run_poller(["refresh"], **METRICS)
    assert metrics["downstream"]["interleave_delay"] == 8000  # µs, as in the Lantiq daemon
    assert metrics["downstream"]["inp"] == 4.5


def test_outside_showtime(run_poller, simulator):
    line = simulator.modem.line
    line.showtime()
    line.add_errors("ds", crc=7)
    line.retrain(FailureReason.LOSS_OF_SIGNAL, LineState.TRAINING)
    (metrics,) = run_poller(["refresh"], **METRICS)
    check_schema(metrics, LANTIQ_SCHEMA)
    assert (metrics["state"], metrics["state_num"], metrics["up"]) == ("Full init", 5, False)
    assert metrics["uptime"] == 0
    assert metrics["downstream"] == {} and metrics["upstream"] == {}
    assert "mode" not in metrics and "standard" not in metrics
    # Counters since start-up stay available.
    assert metrics["errors"]["near"]["cv_c"] == 7


def test_idle(run_poller, simulator):
    (metrics,) = run_poller(["refresh"], **METRICS)
    assert (metrics["state"], metrics["state_num"], metrics["up"]) == ("Idle", 2, False)


def test_no_modem(run_poller):
    (metrics,) = run_poller(["refresh"], mac="02:00:00:00:00:99", **METRICS)
    check_schema(metrics, LANTIQ_SCHEMA)
    assert metrics == {
        "chipset": "Metanoia MT5311", "driver_version": "mt5311d 1.0",
        "state": "Not initialized", "state_num": 0, "up": False, "uptime": 0,
        "atu_c": {}, "downstream": {}, "upstream": {}, "errors": {"near": {}, "far": {}},
    }


def test_unsupported_firmware(run_poller, simulator):
    simulator.modem.reboot(FIRMWARE_UNKNOWN)
    (metrics,) = run_poller(["refresh"], **METRICS)
    assert (metrics["state"], metrics["state_num"]) == ("Exception", 1)
    assert metrics["firmware_version"] == "760101 (2024-01-01 12:00:00)"


@pytest.mark.parametrize(
    ("vendor", "name"),
    [
        ({"country": "b500", "provider": "BDCM", "specific": "86d0",
          "raw": "b5004244434d86d0"}, "Broadcom 134.208"),
        ({"country": "b500", "provider": "BDCM", "specific": "0000",
          "raw": "b5004244434d0000"}, "Broadcom"),
        ({"country": "b500", "provider": "META", "specific": "0000",
          "raw": "b5004d4554410000"}, None),
        ({"country": "0000", "provider": "BDCM", "specific": "0000",
          "raw": "00004244434d0000"}, None),
    ],
)
def test_vendor_names(ucode, vendor, name):
    state = {
        "status": "ok", "showtime": False, "terminal": {"line_state": "idle"},
        "values": {"xdsl2LInvG994VendorId0": vendor}, "counters": {},
    }
    atu_c = ucode.call("mt5311d.metrics", "metrics", state, {})["atu_c"]
    assert atu_c.get("vendor") == name
    assert atu_c["vendor_id"] == list(bytes.fromhex(vendor["raw"]))
