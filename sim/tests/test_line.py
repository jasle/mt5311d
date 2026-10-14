import pytest

from mt5311sim import words
from mt5311sim.device import FIRMWARE_BRANCH_161, FIRMWARE_UNKNOWN, Device, LineState
from mt5311sim.line import Band, FailureReason, Line


@pytest.fixture
def device():
    return Device()


@pytest.fixture
def line(device):
    return Line(device)


def value(device, name):
    (word,) = device.get(name)
    return word


def test_initial_state_is_idle(device, line):
    assert value(device, "xdslTerminal") == 0x000029
    assert value(device, "ModemStatus") == 0x000011
    assert value(device, "xdsl2LineStatusXtuTransSys") == 0
    assert value(device, "xdsl2ChStatusActDataRate2") == 0
    assert value(device, "xdsl2LineBandStatusSnrMargin10") == words.NOT_APPLICABLE


@pytest.mark.parametrize(
    ("state", "terminal"),
    [(LineState.HANDSHAKE, 0x000129), (LineState.TRAINING, 0x000229),
     (LineState.SHOWTIME, 0x000329)],
)
def test_line_state_in_terminal_word(device, line, state, terminal):
    line.set_state(state)
    assert value(device, "xdslTerminal") == terminal


def test_showtime_values_match_observed_encodings(device, line):
    line.showtime()
    # Raw values observed on an RT device in showtime (spec 9.1, 9.3).
    assert value(device, "ModemStatus") == 0x00000F
    assert value(device, "xdsl2LineBandStatusSnrMargin10") == 0x000021
    assert value(device, "xdsl2LineBandStatusSigAtten10") == 0x0000FB
    assert value(device, "xdsl2LineBandStatusLnAtten10") == 0x000103
    assert value(device, "xdsl2LineBandStatusSnrMargin9") == 0x00003C
    assert value(device, "xdsl2LineBandStatusSigAtten9") == words.NOT_APPLICABLE
    assert value(device, "xdsl2LineBandStatusLnAtten9") == words.NOT_APPLICABLE
    assert value(device, "xdsl2LineStatusActAtpDs") == 0x000080
    assert value(device, "xdsl2LineStatusActAtpUs") == 0xFFFFE3
    assert value(device, "xdsl2LineStatusXtuTransSys") == 57
    assert value(device, "xdsl2LineStatusActProfile") == 0x000040
    assert value(device, "nO_DsCombinationTpsTc") == 0x000020
    assert value(device, "xdsl2LineStatusActSnrModeDs") == 1
    assert device.get("xdsl2LInvG994VendorId0") == [0xB50042, 0x44434D, 0x1CC000]
    assert device.get("xdsl2LInvG994VendorId1") == [0xB5004D, 0x455441, 0x000000]


def test_showtime_rates_and_bands(device, line):
    line.status.downstream.data_rate = 116790
    line.status.upstream.inp = 4.5
    line.showtime()
    assert value(device, "xdsl2ChStatusActDataRate2") == 116790
    assert value(device, "xdsl2ChStatusActDataRate0") == 40000
    assert value(device, "xdsl2ChStatusActInp0") == 45
    # Unused bands read 7FFFFE (9.1): US0 and DS4 in the default status.
    assert value(device, "xdsl2LineBandStatusSnrMargin0") == words.NOT_APPLICABLE
    assert value(device, "xdsl2LineBandStatusSnrMargin8") == words.NOT_APPLICABLE
    assert value(device, "xdsl2LineBandStatusLnAtten1") == 152
    assert value(device, "VisibleDsPb0FirstTone") == 33
    assert value(device, "VisibleUsPb4LastTone") == 0


def test_apply_status_while_in_showtime(device, line):
    line.showtime()
    line.status.downstream.total = Band(26.0, 25.5, -1.5)
    line.apply_status()
    assert value(device, "xdsl2LineBandStatusSnrMargin10") == words.signed(-15)
    assert value(device, "xdsl2LineBandStatusLnAtten10") == 260


def test_leaving_showtime_invalidates_status(device, line):
    line.showtime()
    line.retrain(FailureReason.CRC_ERRORS)
    assert value(device, "xdslTerminal") == 0x000029
    assert value(device, "xdsl2ChStatusActDataRate2") == 0
    assert value(device, "xdsl2LineStatusActAtpDs") == words.NOT_APPLICABLE
    assert value(device, "xdsl2MetanoiaRtFailureReasons") == 3


def test_showtime_counters(device, line):
    line.showtime()
    line.error_rates["ds"].crc = 2
    line.error_rates["us"].fec = 5
    line.tick(10)
    assert value(device, "xdslMetanoiaShowtimeSeconds") == 10
    assert value(device, "xdslMetanoiaRtCurrCodingViolations0") == 20
    assert value(device, "xdslMetanoiaRtCurrCorrectedBlocks1") == 50
    assert value(device, "xdslMetanoiaRtCodingViolations0") == 20
    assert value(device, "xdsl2PMChCurr15MCodingViolations2") == 20
    assert value(device, "xdsl2PMChCurr15MCorrectedBlocks0") == 50
    assert value(device, "xdsl2PMLCurr15MEs1") == 10
    assert value(device, "xdsl2PMLCurr15MFecs0") == 10


def test_retrain_resets_showtime_counters_only(device, line):
    line.showtime()
    line.add_errors("ds", crc=7, fec=3)
    line.tick(5)
    line.retrain(FailureReason.LOSS_OF_SIGNAL, LineState.TRAINING)
    line.tick(3)
    line.showtime()
    assert value(device, "xdslMetanoiaShowtimeSeconds") == 0
    assert value(device, "xdslMetanoiaRtCurrCodingViolations0") == 0
    assert value(device, "xdslMetanoiaRtCodingViolations0") == 7
    assert value(device, "xdslMetanoiaRtCorrectedBlocks0") == 3
    assert value(device, "xdsl2PMLCurr15MUas0") == 3


def test_full_inits_count_training_attempts(device, line):
    line.set_state(LineState.HANDSHAKE)
    line.set_state(LineState.TRAINING)
    line.showtime()
    line.retrain(FailureReason.LOSS_OF_POWER)
    line.showtime()
    assert value(device, "xdsl2PMLInitCurr15MFullInits0") == 2
    assert value(device, "xdsl2PMLInitCurr1DayFullInits1") == 2


def test_counters_wrap_at_2_pow_24(device, line):
    line.showtime()
    line.add_errors("ds", crc=0xFFFFFF)
    assert value(device, "xdslMetanoiaRtCurrCodingViolations0") == 0xFFFFFF
    line.add_errors("ds", crc=2)
    assert value(device, "xdslMetanoiaRtCurrCodingViolations0") == 1


def test_negative_error_counts_are_rejected(line):
    with pytest.raises(ValueError):
        line.add_errors("ds", crc=-1)


def test_interval_counters_reset_at_the_end_of_the_interval(device, line):
    line.showtime()
    line.error_rates["ds"].crc = 1
    line.tick(899)
    assert value(device, "xdsl2PMLCurr15MTimeElapsed0") == 899
    assert value(device, "xdsl2PMChCurr15MCodingViolations2") == 899
    line.tick(1)
    assert value(device, "xdsl2PMLCurr15MTimeElapsed0") == 0
    assert value(device, "xdsl2PMChCurr15MCodingViolations2") == 0
    assert value(device, "xdsl2PMLCurr1DayTimeElapsed0") == 900
    assert value(device, "xdsl2PMChCurr1DayCodingViolations2") == 900


def test_branch_161_layout():
    device = Device(FIRMWARE_BRANCH_161)
    line = Line(device)
    line.showtime()
    assert device.peek(0x007016) == 0x0000FB  # xdsl2LineBandStatusSigAtten10 in 1.61


def test_unknown_layout_only_sets_fixed_registers():
    device = Device(FIRMWARE_UNKNOWN)
    line = Line(device)
    line.showtime()
    assert device.peek(0x006C35) == 0x000329
    assert device.peek(0x00001D) == 0x00000F


def test_seconds_counters_since_start_up(device, line):
    line.tick(3)  # not in showtime
    line.showtime()
    line.error_rates["ds"].crc = 1
    line.error_rates["ds"].fec = 2
    line.tick(4)
    line.error_rates["ds"].crc = 0
    line.tick(2)
    line.retrain(FailureReason.LOSS_OF_SIGNAL)
    line.showtime()
    # Since start-up, not reset by the retrain.
    assert value(device, "xdslMetanoiaRtEs0") == 4
    assert value(device, "xdslMetanoiaRtFecs0") == 6
    assert value(device, "xdslMetanoiaRtUas0") == 3
    assert value(device, "xdslMetanoiaRtSes0") == 0
    assert value(device, "xdslMetanoiaRtLoss0") == 0
