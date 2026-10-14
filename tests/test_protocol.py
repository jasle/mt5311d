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


# Responses


@pytest.fixture
def decode(ucode):
    """Decodes a message with the module; None if the module rejects it."""

    def decode(message: bytes):
        source = ("import * as p from 'mt5311d.protocol';\n"
                  "printf('%J', p.decode(hexdec(MESSAGE)));")
        return ucode.run(source, MESSAGE=message.hex())

    return decode


def padded_response(response) -> bytes:
    return sim.pad(sim.encode_response(response), sim.RESPONSE_MIN_LEN)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (sim.ConnectResponse(1, 1), {"type": 0xB1, "seq": 1, "status": 0xE0, "stage": 1}),
        (sim.ConnectResponse(1, 2), {"type": 0xB1, "seq": 1, "status": 0xE1, "stage": 2}),
        (sim.ReadResponse(0xFFFFFFFF, 0x00, (0x474154,)),
         {"type": 0x81, "seq": 0xFFFFFFFF, "status": 0x00, "words": [0x474154]}),
        (sim.ReadResponse(5, 0x00, (0x000000, 0xFFFFFF, 0x7FFFFE)),
         {"type": 0x81, "seq": 5, "status": 0x00, "words": [0, 0xFFFFFF, 0x7FFFFE]}),
        (sim.ReadResponse(6, 0x00, tuple(range(64))),
         {"type": 0x81, "seq": 6, "status": 0x00, "words": list(range(64))}),
        (sim.ReadResponse(7, 0x01), {"type": 0x81, "seq": 7, "status": 0x01, "words": []}),
    ],
)
def test_decode_simulator_responses(decode, response, expected):
    assert decode(padded_response(response)) == expected


def test_decode_responses_from_appendix_b(decode):
    assert decode(h("000e b1 00000001 e0 00000002 95743926"))["stage"] == 1
    assert decode(h("000c b1 00000001 e1 000000000000"))["stage"] == 2
    assert decode(h("0009 81 00000003 00 090718"))["words"] == [0x090718]


def test_error_response_with_payload_has_no_words(decode):
    assert decode(h("0009 81 00000003 01 090718"))["words"] == []


@pytest.mark.parametrize(
    "wire",
    [
        "",
        "0009 81 000001",
        "0005 81 00000001 00",
        "0009 81 00000001 00 4741",
        "0008 81 00000001 00 4741",
        "000e b1 00000001 e0 00000002 95743927",
        "000a b1 00000001 e0 00000002",
        "0006 b1 00000001 00",
        "0006 82 00000001 00",
        "0006 01 00000001 ff 01 006c36 0003",
        # Legacy short format (5.6): control byte without the response bit.
        "0006 01 6c36 455631",
    ],
)
def test_decode_rejects_invalid_responses(decode, wire):
    assert decode(h(wire)) is None


# Response matching (6.2)

DEVICE = "00:0f:c9:1d:98:f2"


@pytest.fixture
def matches(ucode):
    def matches(expected: dict, source: str, response) -> bool:
        source_code = ("import * as p from 'mt5311d.protocol';\n"
                       "printf('%J', p.matches(EXPECTED, SOURCE, RESPONSE));")
        return ucode.run(source_code, EXPECTED=expected, SOURCE=source, RESPONSE=response)

    return matches


READ_REQUEST = {"mac": DEVICE, "type": 0x01, "seq": 1, "count": 2}
READ_OK = {"type": 0x81, "seq": 1, "status": 0x00, "words": [1, 2]}
CONNECT1_REQUEST = {"mac": DEVICE, "type": 0x31, "seq": 1, "stage": 1}
CONNECT1_OK = {"type": 0xB1, "seq": 1, "status": 0xE0, "stage": 1}


@pytest.mark.parametrize(
    ("expected", "source", "response", "result"),
    [
        (READ_REQUEST, DEVICE, READ_OK, True),
        (READ_REQUEST, DEVICE.upper(), READ_OK, True),
        (READ_REQUEST, "00:0f:c9:1d:98:f3", READ_OK, False),
        (READ_REQUEST, DEVICE, {**READ_OK, "seq": 2}, False),
        (READ_REQUEST, DEVICE, {**READ_OK, "words": [1]}, False),
        (READ_REQUEST, DEVICE, {"type": 0x81, "seq": 1, "status": 0x01, "words": []}, True),
        # A late CONNECT response carries the Sequence of the first READ.
        (READ_REQUEST, DEVICE, {"type": 0xB1, "seq": 1, "status": 0xE1, "stage": 2}, False),
        (READ_REQUEST, DEVICE, None, False),
        (READ_REQUEST, None, READ_OK, False),
        (CONNECT1_REQUEST, DEVICE, CONNECT1_OK, True),
        (CONNECT1_REQUEST, DEVICE, {**CONNECT1_OK, "status": 0xE1, "stage": 2}, False),
        ({**CONNECT1_REQUEST, "stage": 2}, DEVICE, CONNECT1_OK, False),
    ],
)
def test_matches(matches, expected, source, response, result):
    assert matches(expected, source, response) is result
