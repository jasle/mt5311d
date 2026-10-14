"""Tests of src/mt5311d/protocol.uc, partly against the simulator's implementation."""

import json

import pytest

from mt5311sim import protocol as sim
from ucode import UcodeError

REQUEST_MIN_LEN = 50


def h(text: str) -> bytes:
    return bytes.fromhex(text.replace(" ", ""))


@pytest.fixture
def encode(ucode):
    """Calls a request function of the module and returns the message as bytes."""

    def encode(function: str, *args) -> bytes:
        source = ("import * as p from 'mt5311d.protocol';\n"
                  f"printf('%J', hexenc(p[{json.dumps(function)}](...ARGS)));")
        return bytes.fromhex(ucode.run(source, ARGS=list(args)))

    return encode


# Requests


@pytest.mark.parametrize(
    ("function", "args", "wire"),
    [
        ("connect1", [1], "0008 31 00000001 ff ffffffff 00000000"),
        ("connect2", [1], "0004 31 00000001 ff 6e6f6961"),
        ("read", [1, [0x006C36]], "0006 01 00000001 ff 01 006c36 0003"),
        ("read", [4, [0x006C33]], "0006 01 00000004 ff 01 006c33 0003"),
        ("disconnect", [7], "0000 50 00000007 ff"),
    ],
)
def test_requests_from_appendix_b(encode, function, args, wire):
    message = encode(function, *args)
    assert message == h(wire).ljust(REQUEST_MIN_LEN, b"\x00")


def test_complete_request_frame_from_appendix_b(encode):
    frame = h(
        "00 0f c9 1d 98 f2 50 7b 9d 42 d0 00 61 20 00 06"
        "01 00 00 00 06 ff 01 00 6c 35 00 03 00 00 00 00"
    ).ljust(64, b"\x00")
    assert encode("read", 6, [0x006C35]) == frame[14:]


def test_read_with_ten_commands_from_section_5_5(encode):
    addresses = [0x006FD7 + 4 * i for i in range(10)]
    message = encode("read", 5, addresses)
    assert message[:20] == h("003c 01 00000005 ff 01 006fd7 0003 01 006fdb 0003")
    # Longer than the minimum, so not padded.
    assert len(message) == 8 + 6 * 10


@pytest.mark.parametrize(
    ("function", "args", "expected"),
    [
        ("connect1", [0], sim.ConnectStage1(0)),
        ("connect1", [0xFFFFFFFF], sim.ConnectStage1(0xFFFFFFFF)),
        ("connect2", [123456], sim.ConnectStage2(123456)),
        ("disconnect", [9], sim.Disconnect(9)),
        ("read", [2, [0x000000]], sim.Read(2, (sim.ReadCommand(sim.Space.X, 0x000000),))),
        ("read", [2, [0xFFFFFF]], sim.Read(2, (sim.ReadCommand(sim.Space.X, 0xFFFFFF),))),
        ("read", [3, list(range(0x007000, 0x007040))],
         sim.Read(3, tuple(sim.ReadCommand(sim.Space.X, a) for a in range(0x007000, 0x007040)))),
    ],
)
def test_simulator_decodes_requests(encode, function, args, expected):
    assert sim.decode_request(encode(function, *args)) == expected


@pytest.mark.parametrize(
    ("function", "args", "error"),
    [
        ("read", [1, []], "1 to 64 addresses"),
        ("read", [1, list(range(65))], "1 to 64 addresses"),
        ("read", [1, 0x006C36], "1 to 64 addresses"),
        ("read", [1, [0x1000000]], "invalid address"),
        ("read", [1, [-1]], "invalid address"),
        ("read", [1, ["6c36"]], "invalid address"),
        ("connect1", [-1], "invalid sequence"),
        ("connect1", [2**32], "invalid sequence"),
    ],
)
def test_invalid_request_arguments(encode, function, args, error):
    with pytest.raises(UcodeError, match=error):
        encode(function, *args)
