import pytest

from mt5311sim.device import (
    FIRMWARE_750202,
    FIRMWARE_BRANCH_161,
    FIRMWARE_UNKNOWN,
    Device,
    DeviceConfig,
    LineState,
    Role,
    terminal_word,
)
from mt5311sim.protocol import (
    ConnectResponse,
    ConnectStage1,
    ConnectStage2,
    Disconnect,
    Read,
    ReadCommand,
    ReadResponse,
    Space,
    decode_response,
    encode_request,
)
from mt5311sim.registers import Layout, register

HOST = bytes.fromhex("020000000001")
OTHER_HOST = bytes.fromhex("020000000003")

ID_BLOCK = range(0x006C31, 0x006C37)
LAYOUT_CHECK = {
    Layout.BRANCH_160: [0x006FEF, 0x006FF3, 0x006FF7, 0x006FFB, 0x006FFF, 0x007003, 0x007011],
    Layout.BRANCH_161: [0x007004, 0x007008, 0x00700C, 0x007010, 0x007014, 0x007018, 0x007026],
}
LAYOUT_EXPECTED = [6, 8, 10, 1, 2, 1, 1]


def send(device, request, host=HOST):
    response = device.handle(host, encode_request(request))
    return None if response is None else decode_response(response)


def connect(device, host=HOST, seq=1):
    assert send(device, ConnectStage1(seq), host) == ConnectResponse(seq, 1)
    assert send(device, ConnectStage2(seq), host) == ConnectResponse(seq, 2)


def read(device, addresses, seq=1, host=HOST):
    return send(device, Read(seq, tuple(ReadCommand(Space.X, a) for a in addresses)), host)


def test_connect_sets_up_a_session():
    device = Device()
    assert device.session_host is None
    connect(device)
    assert device.session_host == HOST


def test_identification_block_of_firmware_750202():
    device = Device()
    connect(device)
    response = read(device, ID_BLOCK)
    assert response == ReadResponse(1, 0x00, (0x750202, 0x090718, 0x173044, 0x801568,
                                              0x000029, 0x474154))


def test_terminal_word():
    # Examples observed in section 9.2.1.
    assert terminal_word(Role.RT, LineState.IDLE) == 0x000029
    assert terminal_word(Role.RT, LineState.SHOWTIME) == 0x000329
    assert terminal_word(Role.OT, LineState.IDLE) == 0x000028


@pytest.mark.parametrize(
    ("firmware", "passing"),
    [(FIRMWARE_750202, {Layout.BRANCH_160}),
     (FIRMWARE_BRANCH_161, {Layout.BRANCH_161}),
     (FIRMWARE_UNKNOWN, set())],
)
def test_layout_check(firmware, passing):
    device = Device(firmware)
    for layout, addresses in LAYOUT_CHECK.items():
        values = [device.peek(a) for a in addresses]
        assert (values == LAYOUT_EXPECTED) == (layout in passing), layout


def test_read_with_64_commands():
    device = Device()
    connect(device)
    addresses = [0x007000 + i for i in range(64)]
    for i, address in enumerate(addresses):
        device.poke(address, i)
    assert read(device, addresses, seq=2) == ReadResponse(2, 0x00, tuple(range(64)))


def test_unset_memory_reads_zero():
    device = Device()
    connect(device)
    assert read(device, [0x001000]).words == (0,)


def test_sequence_is_echoed():
    device = Device()
    connect(device, seq=0xFFFFFFFF)
    assert read(device, [0x006C36], seq=0xFFFFFFFF).seq == 0xFFFFFFFF
    assert read(device, [0x006C36], seq=12345).seq == 12345


@pytest.mark.parametrize(
    "command",
    [ReadCommand(Space.X, 0x006C36, count=6), ReadCommand(4, 0x006C36)],
)
def test_invalid_read_command_gives_error_status(command):
    device = Device(config=DeviceConfig(error_status=0x42))
    connect(device)
    request = Read(3, (ReadCommand(Space.X, 0x006C31), command))
    assert send(device, request) == ReadResponse(3, 0x42)


def test_spaces_y_and_p_read_as_zero():
    device = Device()
    connect(device)
    request = Read(1, (ReadCommand(Space.Y, 0x006C36), ReadCommand(Space.P, 0x006C36)))
    assert send(device, request).words == (0, 0)


def test_stage_2_needs_stage_1():
    device = Device()
    assert send(device, ConnectStage2(1)) is None
    assert send(device, ConnectStage1(1), OTHER_HOST) == ConnectResponse(1, 1)
    assert send(device, ConnectStage2(1)) is None
    assert device.session_host is None


def test_repeated_connect_is_harmless():
    device = Device()
    connect(device)
    connect(device, seq=7)
    assert send(device, ConnectStage2(8)) == ConnectResponse(8, 2)
    assert device.session_host == HOST


@pytest.mark.parametrize("read_without_session", [True, False])
def test_read_without_session(read_without_session):
    device = Device(config=DeviceConfig(read_without_session=read_without_session))
    response = read(device, [0x006C36])
    assert (response is not None) == read_without_session


def test_disconnect_ends_the_session_without_response():
    device = Device(config=DeviceConfig(read_without_session=False))
    connect(device)
    assert send(device, Disconnect(2), OTHER_HOST) is None
    assert device.session_host == HOST
    assert send(device, Disconnect(2)) is None
    assert device.session_host is None
    assert read(device, [0x006C36], seq=3) is None


@pytest.mark.parametrize(
    "message",
    [b"", bytes.fromhex("0007016c360000004f22"), bytes.fromhex("0000 02 00000001 ff")],
)
def test_malformed_and_unknown_messages_are_ignored(message):
    assert Device().handle(HOST, message) is None


def test_set_and_get_registers():
    device = Device(FIRMWARE_BRANCH_161)
    device.set("xdsl2ChStatusActDataRate2", 100000)
    assert device.peek(register("xdsl2ChStatusActDataRate2").addr_161) == 100000
    device.set("xdsl2LInvG994VendorId0", [0xB50042, 0x44434D, 0x1CC000])
    assert device.get("xdsl2LInvG994VendorId0") == [0xB50042, 0x44434D, 0x1CC000]

    with pytest.raises(ValueError, match="3 words"):
        device.set("xdsl2LInvG994VendorId0", 1)
    with pytest.raises(ValueError):
        device.set("xdsl2ChStatusActDataRate2", -1)


def test_registers_need_a_known_layout():
    device = Device(FIRMWARE_UNKNOWN)
    with pytest.raises(LookupError):
        device.set("xdsl2ChStatusActDataRate2", 1)


def test_load_firmware_resets_memory_and_session():
    device = Device()
    connect(device)
    device.set("xdsl2ChStatusActDataRate2", 100000)
    device.load_firmware(FIRMWARE_BRANCH_161)
    assert device.session_host is None
    assert device.get("xdsl2ChStatusActDataRate2") == [0]
    assert device.peek(0x006C32) == 0x080217


def test_ot_role():
    device = Device(role=Role.OT)
    assert device.peek(0x006C35) == 0x000028
