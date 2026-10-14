"""Tests of src/mt5311d/poller.uc against the simulator.

Changes to the simulated modem are tied to the poller's traffic with request
hooks: on_cycle(n, action) runs action when the n-th poll cycle starts reading,
before the modem answers.
"""

import pytest

from conftest import DAEMON_INTERFACE, ID_START, MAX_COMMANDS
from mt5311sim import protocol as sim
from mt5311sim.device import FIRMWARE_BRANCH_161, FIRMWARE_UNKNOWN, LineState, Role
from mt5311sim.line import FailureReason

REFRESH = ["refresh"]


def test_first_refresh_in_showtime(run_poller, simulator):
    line = simulator.modem.line
    line.showtime()
    line.add_errors("ds", crc=4, fec=56)
    (state,) = run_poller(REFRESH)

    assert state["status"] == "ok"
    assert state["layout"] == "1.60"
    assert state["firmware"]["date"] == "2018-09-07"
    assert state["terminal"]["line_state"] == "showtime"
    assert state["showtime"] is True
    assert state["values"]["xdsl2ChStatusActDataRate2"] == line.status.downstream.data_rate
    assert state["values"]["xdsl2LineBandStatusSnrMargin10"] == 3.3
    assert state["values"]["xdsl2LInvVersionNumber1"] == line.status.own_version
    assert state["counters"]["xdslMetanoiaRtCurrCodingViolations0"] == 4
    assert state["counters"]["xdslMetanoiaRtCurrCorrectedBlocks0"] == 56
    assert state["failure_reason"] == {"value": 0, "name": "none"}
    assert state["updated"] > 0


def test_outside_showtime(run_poller, simulator):
    simulator.modem.line.set_state(LineState.TRAINING)
    (state,) = run_poller(REFRESH)
    assert state["status"] == "ok"
    assert state["showtime"] is False
    assert state["terminal"]["line_state"] == "training"
    # Measurement values are only meaningful in showtime (7.3), rates included.
    assert state["values"]["xdsl2ChStatusActDataRate2"] is None
    assert state["values"]["xdsl2LineStatusActAtpDs"] is None
    # Only the counters since start-up; showtime counters belong to a showtime.
    assert "xdslMetanoiaRtCodingViolations0" in state["counters"]
    assert not [name for name in state["counters"]
                if "Curr" in name or name == "xdslMetanoiaShowtimeSeconds"]


def test_retrain(run_poller, simulator, on_cycle):
    line = simulator.modem.line
    line.showtime()
    line.add_errors("ds", fec=100)
    on_cycle(2, lambda: line.retrain(FailureReason.LOSS_OF_POWER))
    on_cycle(3, line.showtime)

    states = run_poller(REFRESH, REFRESH, REFRESH)
    assert [s["showtime"] for s in states] == [True, False, True]
    assert states[1]["failure_reason"]["name"] == "loss_of_power"
    assert states[2]["failure_reason"]["name"] == "loss_of_power"
    assert states[2]["counters"]["xdslMetanoiaRtCurrCorrectedBlocks0"] == 0


def test_counters_are_extended_beyond_24_bits(run_poller, simulator, on_cycle):
    line = simulator.modem.line
    line.showtime()
    line.add_errors("ds", fec=0xFFFFF0)
    on_cycle(2, lambda: line.add_errors("ds", fec=0x20))
    on_cycle(3, lambda: line.add_errors("ds", fec=0xFFFFFF))

    states = run_poller(REFRESH, REFRESH, REFRESH)
    assert [s["counters"]["xdslMetanoiaRtCurrCorrectedBlocks0"] for s in states] == [
        0xFFFFF0, 0x1000010, 0x200000F,
    ]
    # The modem's own counter wrapped.
    assert states[1]["values"]["xdslMetanoiaRtCurrCorrectedBlocks0"] == 0x10


def test_counters_since_start_up_continue_across_a_retrain(run_poller, simulator, on_cycle):
    line = simulator.modem.line
    line.showtime()
    line.tick(60)
    line.add_errors("ds", crc=0xFFFFF0, fec=10)

    def retrain():
        line.retrain(FailureReason.CRC_ERRORS)
        line.showtime()
        line.tick(5)  # the showtime duration decreases, so the retrain is detected
        line.add_errors("ds", crc=0x20, fec=5)

    on_cycle(2, retrain)
    states = run_poller(REFRESH, REFRESH)
    totals = [(s["counters"]["xdslMetanoiaRtCodingViolations0"],
               s["counters"]["xdslMetanoiaRtCorrectedBlocks0"]) for s in states]
    current = [s["counters"]["xdslMetanoiaRtCurrCorrectedBlocks0"] for s in states]
    # Across the retrain and the overflow of the modem's 24-bit counter.
    assert totals == [(0xFFFFF0, 10), (0x1000010, 15)]
    assert current == [10, 5]


def test_seconds_counters_since_start_up(run_poller, simulator):
    line = simulator.modem.line
    line.tick(3)
    line.showtime()
    line.error_rates["ds"].crc = 1
    line.tick(4)
    (state,) = run_poller(REFRESH)
    counters = state["counters"]
    assert (counters["xdslMetanoiaRtEs0"], counters["xdslMetanoiaRtUas0"]) == (4, 3)


def test_whole_retrain_between_two_cycles(run_poller, simulator, on_cycle):
    line = simulator.modem.line
    line.showtime()
    line.tick(100)
    line.add_errors("ds", fec=500)

    def retrain():
        line.retrain(FailureReason.CRC_ERRORS)
        line.showtime()
        line.tick(10)
        line.add_errors("ds", fec=7)

    on_cycle(2, retrain)
    states = run_poller(REFRESH, REFRESH)
    # The showtime duration went down, so the counters start again (7.2).
    assert states[1]["counters"]["xdslMetanoiaShowtimeSeconds"] == 10
    assert states[1]["counters"]["xdslMetanoiaRtCurrCorrectedBlocks0"] == 7
    assert states[1]["failure_reason"]["name"] == "crc_errors"


def test_firmware_change(run_poller, simulator, on_cycle):
    modem = simulator.modem
    modem.line.showtime()

    def change():
        modem.reboot(FIRMWARE_BRANCH_161)
        modem.line.showtime()

    on_cycle(2, change)
    states = run_poller(REFRESH, ["wait", 150], REFRESH)
    assert states[0]["layout"] == "1.60"
    # The changed identification leads to a new session and layout selection in
    # the same cycle.
    assert states[1]["status"] == "ok"
    assert states[1]["layout"] == "1.61"
    assert states[1]["firmware"]["date"] == "2017-08-02"
    assert states[1]["values"]["xdsl2LineBandStatusSigAtten10"] == 25.1
    connects = [r for r in modem.received if isinstance(r.request, sim.ConnectStage1)]
    assert len(connects) == 2


def test_reboot_without_session(run_poller, simulator, on_cycle):
    modem = simulator.modem
    # Assume that the device ignores READ without a session after a reboot (6.4).
    modem.device.config.read_without_session = False
    modem.line.showtime()
    on_cycle(2, modem.reboot)

    states = run_poller(REFRESH, ["wait", 150], REFRESH)
    assert states[1]["status"] == "ok"
    assert states[1]["showtime"] is False


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        (lambda m: m.reboot(FIRMWARE_UNKNOWN),
         "firmware not supported: no layout passes the layout check"),
        (lambda m: (setattr(m.device, "role", Role.OT), m.line.apply_status()),
         "device runs as OT (network side); only RT is supported"),
    ],
)
def test_unsupported(run_poller, simulator, setup, reason):
    setup(simulator.modem)
    states = run_poller(REFRESH, REFRESH)
    assert [(s["status"], s["reason"]) for s in states] == [("unsupported", reason)] * 2
    assert "values" not in states[0]


def test_modem_not_reachable(run_poller):
    states = run_poller(REFRESH, REFRESH, ["wait", 150], REFRESH,
                        mac="02:00:00:00:00:99", reconnect_delay=100)
    assert [s["reason"] for s in states] == [
        "no response to CONNECT stage 1",
        "waiting to reconnect",
        "no response to CONNECT stage 1",
    ]
    assert {s["status"] for s in states} == {"error"}


# Triggering of cycles


def poll_reads(simulator):
    """Number of poll cycles that read from the modem."""
    return sum(1 for r in simulator.modem.received
               if isinstance(r.request, sim.Read) and r.request.commands[0].address == ID_START
               and len(r.request.commands) == MAX_COMMANDS)


def test_refresh_within_max_age_returns_the_last_state(run_poller, simulator):
    states = run_poller(REFRESH, REFRESH, ["wait", 300], REFRESH, max_age=200)
    assert states[0] == states[1]
    assert states[2]["updated"] > states[1]["updated"]
    assert poll_reads(simulator) == 2


def test_concurrent_refreshes_share_one_cycle(run_poller, simulator):
    (states,) = run_poller(["refresh", 3])
    assert len(states) == 3
    assert states[0] == states[1] == states[2]
    assert poll_reads(simulator) == 1


def test_background_cycles(run_poller, simulator):
    run_poller(["start"], ["wait", 1000], ["stop"], interval=200)
    # One cycle at start, then one per interval after the end of each cycle.
    assert 4 <= poll_reads(simulator) <= 6
    count = poll_reads(simulator)

    run_poller(["start"], ["stop"], ["wait", 500], interval=100)
    assert poll_reads(simulator) == count + 1


def test_refresh_during_background_cycle(run_poller, simulator):
    # start() begins a cycle; the refresh waits for it instead of starting another.
    (state,) = run_poller(["start"], REFRESH, ["stop"], interval=10000)
    assert state["status"] == "ok"
    assert poll_reads(simulator) == 1


# Failed requests (6.4)

ATP_DS = 0x006F24  # xdsl2LineStatusActAtpDs in layout 1.60
VENDOR_ID0 = 0x0079C8  # xdsl2LInvG994VendorId0, 3 words, in layout 1.60


def reads_of(simulator, address):
    return sum(1 for r in simulator.modem.received if isinstance(r.request, sim.Read)
               and any(c.address == address for c in r.request.commands))


def test_register_with_error_response_is_skipped(run_poller, simulator):
    modem = simulator.modem
    modem.line.showtime()
    modem.faults.fail_reads([ATP_DS], status=0x05)

    states = run_poller(REFRESH, REFRESH)
    for state in states:
        assert state["status"] == "ok"
        assert state["values"]["xdsl2LineStatusActAtpDs"] is None
        assert state["values"]["xdsl2LineStatusActAtpUs"] == -2.9
        assert state["unreadable"] == ["xdsl2LineStatusActAtpDs"]
    # Found by reading the failed request's addresses one by one in the first
    # cycle, then left out; the session stays.
    assert reads_of(simulator, ATP_DS) == 2
    assert len([r for r in modem.received if isinstance(r.request, sim.ConnectStage1)]) == 1


def test_register_without_response_is_suspended(run_poller, simulator):
    modem = simulator.modem
    modem.line.showtime()
    modem.faults.drop(count=None, when=lambda r: isinstance(r, sim.Read) and any(
        c.address == ATP_DS for c in r.commands))

    states = run_poller(REFRESH, REFRESH, ["wait", 400], REFRESH,
                        holdoff=300, holdoff_max=10000, watchdog=20000)
    assert [s["suspended"] for s in states] == [["xdsl2LineStatusActAtpDs"]] * 3
    assert states[0]["values"]["xdsl2LineStatusActAtpDs"] is None
    assert states[0]["values"]["xdsl2LineStatusActAtpUs"] == -2.9
    # Cycle 1: 3 attempts in the full request, 3 single; cycle 2 leaves it out;
    # cycle 3 after the hold-off reads it again.
    assert reads_of(simulator, ATP_DS) == 12


def test_suspended_register_is_read_again_after_the_holdoff(run_poller, simulator):
    modem = simulator.modem
    modem.line.showtime()
    modem.faults.drop(count=6, when=lambda r: isinstance(r, sim.Read) and any(
        c.address == ATP_DS for c in r.commands))

    states = run_poller(REFRESH, ["wait", 400], REFRESH, holdoff=300, watchdog=20000)
    assert states[0]["suspended"] == ["xdsl2LineStatusActAtpDs"]
    assert states[1]["suspended"] == []
    assert states[1]["values"]["xdsl2LineStatusActAtpDs"] == 12.8


def test_multi_word_register_with_failed_word(run_poller, simulator):
    modem = simulator.modem
    modem.line.showtime()
    modem.faults.fail_reads([VENDOR_ID0 + 1])
    (state,) = run_poller(REFRESH)
    assert state["values"]["xdsl2LInvG994VendorId0"] is None
    assert state["values"]["xdsl2LInvG994VendorId1"]["provider"] == "META"
    assert state["unreadable"] == ["xdsl2LInvG994VendorId0"]


def test_unreadable_registers_are_forgotten_with_a_new_layout(run_poller, simulator, on_cycle):
    modem = simulator.modem
    modem.line.showtime()
    modem.faults.fail_reads([ATP_DS], count=2)

    def change():
        modem.reboot(FIRMWARE_BRANCH_161)
        modem.line.showtime()

    on_cycle(2, change)
    states = run_poller(REFRESH, REFRESH)
    assert states[0]["unreadable"] == ["xdsl2LineStatusActAtpDs"]
    assert states[1]["layout"] == "1.61"
    assert states[1]["unreadable"] == []
    assert states[1]["values"]["xdsl2LineStatusActAtpDs"] == 12.8


def test_on_update_after_every_cycle(ucode, simulator):
    source = """
        import * as uloop from 'uloop';
        import * as session from 'mt5311d.session';
        import * as poller from 'mt5311d.poller';

        uloop.init();
        const s = session.create(SESSION);
        s.open();

        const updates = [];
        const p = poller.create(s, {
            interval: 100, max_age: 0,
            on_update: (state) => push(updates, state.status),
        });

        p.start();
        uloop.timer(350, () => { p.stop(); uloop.end(); });
        uloop.run();
        s.close();
        printf('%J', updates);
    """
    updates = ucode.run(source, SESSION={"interface": DAEMON_INTERFACE, "mac": simulator.mac})
    # One cycle at start, then one per interval after the end of each cycle.
    assert 3 <= len(updates) <= 4
    assert set(updates) == {"ok"}
