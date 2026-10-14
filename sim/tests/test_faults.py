import pytest

from mt5311sim.device import FIRMWARE_BRANCH_161, LineState
from mt5311sim.faults import reads
from mt5311sim.modem import Modem
from mt5311sim.protocol import (
    ConnectResponse,
    ConnectStage1,
    ConnectStage2,
    Read,
    ReadCommand,
    ReadResponse,
    Space,
    decode_response,
    encode_request,
)

HOST = bytes.fromhex("020000000001")


def send(modem, request):
    replies = modem.handle(HOST, encode_request(request))
    return [(decode_response(r.message), r.delay) for r in replies]


def read(addresses, seq=1):
    return Read(seq, tuple(ReadCommand(Space.X, a) for a in addresses))


@pytest.fixture
def modem():
    modem = Modem()
    send(modem, ConnectStage1(1))
    send(modem, ConnectStage2(1))
    return modem


def test_no_faults(modem):
    assert send(modem, read([0x006C36])) == [(ReadResponse(1, 0x00, (0x474154,)), 0.0)]


def test_drop_next_response(modem):
    modem.faults.drop()
    assert send(modem, read([0x006C36])) == []
    assert len(send(modem, read([0x006C36]))) == 1


def test_drop_matching_requests_only(modem):
    modem.faults.drop(count=None, when=reads(0x006C31))
    assert send(modem, read([0x006C36])) != []
    assert send(modem, read([0x006C36, 0x006C31])) == []
    assert send(modem, read([0x006C31], seq=2)) == []


def test_drop_connect(modem):
    modem.faults.drop(count=2, when=lambda r: isinstance(r, ConnectStage1))
    assert send(modem, ConnectStage1(5)) == []
    assert send(modem, ConnectStage1(5)) == []
    assert send(modem, ConnectStage1(5)) == [(ConnectResponse(5, 1), 0.0)]


def test_delay(modem):
    modem.faults.delay(0.3)
    assert send(modem, read([0x006C36])) == [(ReadResponse(1, 0x00, (0x474154,)), 0.3)]
    assert send(modem, read([0x006C36]))[0][1] == 0.0


def test_fail_reads_with_error_status(modem):
    modem.faults.fail_reads([0x006C33], status=0x05)
    assert send(modem, read([0x006C31, 0x006C33])) == [(ReadResponse(1, 0x05), 0.0)]
    assert send(modem, read([0x006C31])) == [(ReadResponse(1, 0x00, (0x750202,)), 0.0)]


def test_fail_reads_default_status(modem):
    modem.faults.fail_reads([0x006C33], count=1)
    assert send(modem, read([0x006C33]))[0][0].status == modem.device.config.error_status
    assert send(modem, read([0x006C33]))[0][0].status == 0x00


def test_clear(modem):
    modem.faults.drop(count=None)
    modem.faults.clear()
    assert send(modem, read([0x006C36])) != []


def test_malformed_messages_are_ignored(modem):
    assert modem.handle(HOST, b"\x00\x07\x01") == []


def test_reboot_loses_session_line_state_and_counters(modem):
    modem.device.config.read_without_session = False
    modem.line.status.downstream.data_rate = 50000
    modem.line.showtime()
    modem.line.add_errors("ds", crc=3)

    modem.reboot()

    assert modem.device.session_host is None
    assert send(modem, read([0x006C35])) == []
    assert modem.line.state == LineState.IDLE
    assert modem.device.get("xdslMetanoiaRtCodingViolations0") == [0]
    modem.line.showtime()
    assert modem.device.get("xdsl2ChStatusActDataRate2") == [50000]


def test_reboot_with_other_firmware(modem):
    modem.reboot(FIRMWARE_BRANCH_161)
    assert modem.device.peek(0x006C32) == 0x080217
    modem.line.showtime()
    assert modem.device.peek(0x007016) == 0x0000FB  # SigAtten10 at its 1.61 address


def test_received_requests_are_recorded(modem):
    # The fixture sent CONNECT stage 1 and 2.
    modem.received.clear()
    send(modem, read([0x006C36], seq=5))
    modem.handle(HOST, b"\x00\x07\x01")  # malformed, not recorded
    assert [(r.host, r.request) for r in modem.received] == [(HOST, read([0x006C36], seq=5))]
    assert modem.received[0].time > 0


def test_request_hooks_run_before_the_response(modem):
    seen = []

    def hook(received):
        seen.append(received.request)
        modem.line.showtime()

    modem.on_request(hook)
    assert send(modem, read([0x006C35])) == [(ReadResponse(1, 0x00, (0x000329,)), 0.0)]
    assert seen == [read([0x006C35])]

    modem.hooks.remove(hook)
    send(modem, read([0x006C35]))
    assert len(seen) == 1
