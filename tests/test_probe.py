"""Tests of tools/mt5311-probe.uc against the simulator."""

import json

import pytest

from conftest import DAEMON_INTERFACE
from mt5311sim.device import FIRMWARE_BRANCH_161, FIRMWARE_UNKNOWN
from mt5311sim.line import FailureReason
from ucode import REPO, UcodeError

PROBE = REPO / "tools" / "mt5311-probe.uc"


@pytest.fixture
def probe(ucode, simulator):
    def probe(mac=None):
        return json.loads(ucode.run_script(PROBE, DAEMON_INTERFACE, mac or simulator.mac))

    return probe


def test_showtime(probe, simulator):
    line = simulator.modem.line
    line.showtime()
    line.add_errors("ds", crc=12, fec=345)
    result = probe()

    assert result["firmware"] == {"version": 0x750202, "major": 0x75, "minor": 0x0202,
                                  "date": "2018-09-07", "time": "17:30:44"}
    assert result["signature_valid"] is True
    assert result["terminal"]["line_state"] == "showtime"
    assert result["layout"]["layout"] == "1.60"

    v = result["values"]
    assert v["xdsl2ChStatusActDataRate2"] == line.status.downstream.data_rate
    assert v["xdsl2LineBandStatusSnrMargin10"] == line.status.downstream.total.snr_margin
    assert v["xdsl2LineStatusActAtpUs"] == line.status.upstream.transmit_power
    assert v["xdsl2LineStatusActProfile"]["name"] == line.status.profile
    assert v["xdsl2LInvG994VendorId0"]["provider"] == "BDCM"
    assert v["xdsl2LInvVersionNumber1"] == line.status.own_version
    assert v["xdslMetanoiaRtCurrCodingViolations0"] == 12
    assert v["xdslMetanoiaRtCurrCorrectedBlocks0"] == 345


def test_idle_after_retrain(probe, simulator):
    simulator.modem.line.showtime()
    simulator.modem.line.retrain(FailureReason.LOSS_OF_POWER)
    result = probe()
    assert result["terminal"]["line_state"] == "idle"
    assert result["values"]["xdsl2LineBandStatusSnrMargin10"] is None
    assert result["values"]["xdsl2MetanoiaRtFailureReasons"]["name"] == "loss_of_power"


def test_layout_161(probe, simulator):
    simulator.modem.reboot(FIRMWARE_BRANCH_161)
    simulator.modem.line.showtime()
    result = probe()
    assert result["layout"]["layout"] == "1.61"
    assert result["values"]["xdsl2LineBandStatusSigAtten10"] == 25.1


def test_unsupported_firmware(probe, simulator):
    simulator.modem.reboot(FIRMWARE_UNKNOWN)
    result = probe()
    assert result["layout"] == {"layout": None, "passed": [],
                                "reason": "no layout passes the layout check"}
    assert "values" not in result


def test_no_modem(probe):
    with pytest.raises(UcodeError, match="no response to CONNECT stage 1"):
        probe(mac="02:00:00:00:00:99")


def test_usage(ucode):
    with pytest.raises(UcodeError, match="usage"):
        ucode.run_script(PROBE, DAEMON_INTERFACE)
