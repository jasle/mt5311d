"""Tests of src/mt5311d/session.uc against the simulator, over real frames."""

import socket
import struct
import time

import pytest

from conftest import DAEMON_INTERFACE, MODEM_INTERFACE
from mt5311sim import protocol as sim
from mt5311sim.faults import reads
from mt5311sim.transport import open_in_netns
from ucode import UcodeError

# Runs STEPS one after another with a session and prints their results:
#   [ 'connect' ]          -> { ok, reason }
#   [ 'read', addresses ]  -> the result of session.read()
DRIVER = """
    import * as uloop from 'uloop';
    import * as session from 'mt5311d.session';

    uloop.init();

    const s = session.create(CONFIG);
    const error = s.open();
    if (error)
        die(error);

    const results = [];
    let i = 0;

    function next() {
        if (i >= length(STEPS)) {
            uloop.end();
            return;
        }

        const step = STEPS[i++];

        if (step[0] == 'connect')
            s.connect((ok, reason) => { push(results, { ok, reason }); next(); });
        else
            s.read(step[1], (result) => { push(results, result); next(); });
    }

    uloop.timer(WATCHDOG, () => die('test driver timed out'));
    next();
    uloop.run();
    s.close();
    printf('%J', results);
"""

ID_BLOCK = [0x006C31, 0x006C32, 0x006C33, 0x006C34, 0x006C35, 0x006C36]
ID_WORDS = [0x750202, 0x090718, 0x173044, 0x801568, 0x000029, 0x474154]
CONNECTED = {"ok": True, "reason": None}


@pytest.fixture
def run_session(ucode, simulator):
    def run_session(*steps, mac=None, watchdog=5000, **options):
        config = {"interface": DAEMON_INTERFACE, "mac": mac or simulator.mac, **options}
        return ucode.run(DRIVER, CONFIG=config, STEPS=list(steps), WATCHDOG=watchdog)

    return run_session


def requests(simulator, kind=sim.Read):
    return [r for r in simulator.modem.received if isinstance(r.request, kind)]


def test_connect_and_read(run_session, simulator):
    assert run_session(["connect"], ["read", ID_BLOCK]) == [
        CONNECTED,
        {"status": "ok", "words": ID_WORDS},
    ]


def test_mac_address_in_upper_case(run_session, simulator):
    assert run_session(["connect"], mac=simulator.mac.upper()) == [CONNECTED]


def test_read_with_64_commands(run_session, simulator):
    addresses = [0x007000 + i for i in range(64)]
    for i, address in enumerate(addresses):
        simulator.modem.device.poke(address, i)
    assert run_session(["connect"], ["read", addresses])[1] == {
        "status": "ok", "words": list(range(64)),
    }


def test_sequence_numbers(run_session, simulator):
    run_session(["connect"], ["read", [0x006C31]], ["read", [0x006C32]], ["read", [0x006C33]])
    # CONNECT does not advance the counter; the first READ shares its value (6.2).
    connects = requests(simulator, (sim.ConnectStage1, sim.ConnectStage2))
    assert [r.request.seq for r in connects] == [1, 1]
    assert [r.request.seq for r in requests(simulator)] == [1, 2, 3]


def test_lost_response_is_retransmitted(run_session, simulator):
    simulator.modem.faults.drop(count=2, when=reads(0x006C36))
    assert run_session(["connect"], ["read", [0x006C36]])[1] == {
        "status": "ok", "words": [0x474154],
    }
    # Three attempts with the same Sequence (6.3).
    assert [r.request.seq for r in requests(simulator)] == [1, 1, 1]


def test_timeout_after_all_attempts(run_session, simulator):
    simulator.modem.faults.drop(count=None, when=reads(0x006C36))
    results = run_session(["connect"], ["read", [0x006C36]], ["read", [0x006C31]])
    assert results[1:] == [{"status": "timeout"}, {"status": "ok", "words": [0x750202]}]
    # The counter advances after an abandoned request, too.
    assert [r.request.seq for r in requests(simulator)] == [1, 1, 1, 2]


def test_attempts_and_timeout_are_configurable(run_session, simulator):
    simulator.modem.faults.drop(count=None, when=reads(0x006C36))
    start = time.monotonic()
    run_session(["connect"], ["read", [0x006C36]], attempts=2, timeout=100)
    assert len(requests(simulator)) == 2
    assert time.monotonic() - start < 2


def test_late_response_is_not_taken_for_the_next_request(run_session, simulator):
    # The responses to all attempts of the first READ arrive after it was abandoned,
    # while the second READ is outstanding.
    simulator.modem.faults.delay(0.7, count=3, when=reads(0x006C36))
    results = run_session(["connect"], ["read", [0x006C36]], ["read", [0x006C31]],
                          ["read", [0x006C32]])
    assert results[1:] == [
        {"status": "timeout"},
        {"status": "ok", "words": [0x750202]},
        {"status": "ok", "words": [0x090718]},
    ]


def test_error_response(run_session, simulator):
    simulator.modem.faults.fail_reads([0x006C33], status=0x05)
    assert run_session(["connect"], ["read", [0x006C31, 0x006C33]])[1] == {
        "status": "error", "code": 0x05,
    }
    # Error responses are not retransmitted (6.2).
    assert len(requests(simulator)) == 1


def test_connect_without_response(run_session, simulator):
    simulator.modem.faults.drop(count=None, when=lambda r: isinstance(r, sim.ConnectStage2))
    assert run_session(["connect"]) == [
        {"ok": False, "reason": "no response to CONNECT stage 2"},
    ]


def test_minimum_interval_between_requests(run_session, simulator):
    run_session(["connect"], *[["read", [0x006C31]]] * 5, interval=20)
    times = [r.time for r in simulator.modem.received]
    gaps = [b - a for a, b in zip(times, times[1:])]
    # The modem answers within a millisecond, so each gap is mostly the interval.
    assert min(gaps) >= 0.019, gaps


@pytest.fixture
def inject(simulator, container_netns):
    """Sends a raw Ethernet frame to the daemon from a chosen source MAC address."""
    sock = open_in_netns(container_netns, lambda: _raw_socket(MODEM_INTERFACE))
    daemon_mac = _interface_mac(container_netns, DAEMON_INTERFACE)

    def inject(source_mac: str, response) -> None:
        payload = sim.pad(sim.encode_response(response), sim.RESPONSE_MIN_LEN)
        header = (daemon_mac + bytes.fromhex(source_mac.replace(":", ""))
                  + struct.pack(">H", sim.ETHERTYPE))
        sock.send(header + payload)

    yield inject
    sock.close()


def _raw_socket(interface):
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
    sock.bind((interface, 0))
    return sock


def _interface_mac(netns, interface):
    def open_socket():
        sock = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(sim.ETHERTYPE))
        sock.bind((interface, sim.ETHERTYPE))
        return sock

    sock = open_in_netns(netns, open_socket)
    try:
        return sock.getsockname()[4]
    finally:
        sock.close()


def test_foreign_frames_are_ignored(run_session, simulator, inject):
    # When the READ arrives, a foreign station and the modem itself (with a wrong
    # Sequence) answer first; the real response follows 50 ms later.
    def forge(request):
        if not isinstance(request, sim.Read):
            return False
        inject("02:00:00:00:00:99", sim.ReadResponse(request.seq, 0x00, (0x111111,)))
        inject(simulator.mac, sim.ReadResponse(request.seq + 1, 0x00, (0x222222,)))
        inject(simulator.mac, sim.ConnectResponse(request.seq, 2))
        return True

    simulator.modem.faults.delay(0.05, count=1, when=forge)
    assert run_session(["connect"], ["read", [0x006C36]])[1] == {
        "status": "ok", "words": [0x474154],
    }


def test_open_fails_on_unknown_interface(ucode):
    with pytest.raises(UcodeError, match="bind to nope0"):
        ucode.run(DRIVER, CONFIG={"interface": "nope0", "mac": "02:00:00:00:00:01"},
                  STEPS=[], WATCHDOG=1000)


def test_second_request_while_one_is_outstanding(ucode, simulator):
    source = """
        import * as uloop from 'uloop';
        import * as session from 'mt5311d.session';
        uloop.init();
        const s = session.create(CONFIG);
        s.open();
        s.read([ 0x006c31 ], () => null);
        s.read([ 0x006c32 ], () => null);
    """
    with pytest.raises(UcodeError, match="a request is already outstanding"):
        ucode.run(source, CONFIG={"interface": DAEMON_INTERFACE, "mac": simulator.mac})


def test_close_from_a_callback(ucode, simulator):
    source = """
        import * as uloop from 'uloop';
        import * as session from 'mt5311d.session';
        uloop.init();
        const s = session.create(CONFIG);
        s.open();
        let result = null;
        s.connect((ok) => { result = ok; s.close(); uloop.end(); });
        uloop.timer(2000, () => uloop.end());
        uloop.run();
        printf('%J', result);
    """
    assert ucode.run(source, CONFIG={"interface": DAEMON_INTERFACE, "mac": simulator.mac}) is True
