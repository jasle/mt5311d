"""Tests of src/mt5311d/poller.uc against the simulator.

Changes to the simulated modem are tied to the poller's traffic with request
hooks: on_cycle(n, action) runs action when the n-th poll cycle starts reading,
before the modem answers.
"""

import pytest

from conftest import DAEMON_INTERFACE
from mt5311sim import protocol as sim
from mt5311sim.device import FIRMWARE_BRANCH_161, FIRMWARE_UNKNOWN, LineState, Role
from mt5311sim.line import FailureReason

# Runs STEPS with a poller and prints the state after each refresh:
#   [ 'refresh' ]     -> the state passed to the refresh callback
#   [ 'wait', ms ]    -> nothing
DRIVER = """
    import * as uloop from 'uloop';
    import * as session from 'mt5311d.session';
    import * as poller from 'mt5311d.poller';

    uloop.init();

    const s = session.create(SESSION);
    const error = s.open();
    if (error)
        die(error);

    const p = poller.create(s, OPTIONS);
    const results = [];
    let i = 0;

    function next() {
        if (i >= length(STEPS)) {
            uloop.end();
            return;
        }

        const step = STEPS[i++];

        if (step[0] == 'refresh')
            p.refresh((state) => { push(results, state); next(); });
        else
            uloop.timer(step[1], next);
    }

    uloop.timer(WATCHDOG, () => die('test driver timed out'));
    next();
    uloop.run();
    s.close();
    printf('%J', results);
"""

ID_START = 0x006C31
MAX_COMMANDS = 64


@pytest.fixture
def run_poller(ucode, simulator):
    def run_poller(*steps, mac=None, watchdog=10000, **options):
        options.setdefault("reconnect_delay", 100)
        return ucode.run(DRIVER, SESSION={"interface": DAEMON_INTERFACE,
                                          "mac": mac or simulator.mac},
                         OPTIONS=options, STEPS=list(steps), WATCHDOG=watchdog)

    return run_poller


@pytest.fixture
def on_cycle(simulator):
    """Runs action when the n-th poll cycle (counted from 1) starts reading."""
    cycles = 0
    actions = {}

    # A poll cycle starts with a full READ that begins with the identification
    # block; the READ of the layout selection has only 20 commands.
    def hook(received):
        nonlocal cycles
        request = received.request
        if (isinstance(request, sim.Read) and request.commands[0].address == ID_START
                and len(request.commands) == MAX_COMMANDS):
            cycles += 1
            if cycles in actions:
                actions[cycles]()

    simulator.modem.on_request(hook)

    def on_cycle(n, action):
        actions[n] = action

    return on_cycle


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
    assert state["counters"] == {}


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
