import pytest

from mt5311sim.protocol import (
    REQUEST_MIN_LEN,
    RESPONSE_MIN_LEN,
    ConnectResponse,
    ConnectStage1,
    ConnectStage2,
    Disconnect,
    ProtocolError,
    Read,
    ReadCommand,
    ReadResponse,
    Space,
    decode_request,
    decode_response,
    encode_request,
    encode_response,
    pad,
)


def h(text: str) -> bytes:
    return bytes.fromhex(text.replace(" ", ""))


# Messages from Appendix B (padding omitted there) and section 5.5.
ID_BLOCK = [0x006C31, 0x006C32, 0x006C33, 0x006C34, 0x006C35, 0x006C36]
REQUEST_VECTORS = [
    (ConnectStage1(1), "0008 31 00000001 ff ffffffff 00000000"),
    (ConnectStage2(1), "0004 31 00000001 ff 6e6f6961"),
    (Read(1, (ReadCommand(Space.X, 0x006C36),)), "0006 01 00000001 ff 01 006c36 0003"),
    (Read(5, (ReadCommand(Space.X, 0x006FD7), ReadCommand(Space.X, 0x006FDB))),
     "000c 01 00000005 ff 01 006fd7 0003 01 006fdb 0003"),
    (Disconnect(7), "0000 50 00000007 ff"),
]
RESPONSE_VECTORS = [
    (ConnectResponse(1, 1), "000e b1 00000001 e0 00000002 95743926"),
    (ConnectResponse(1, 2), "000c b1 00000001 e1 000000000000"),
    (ReadResponse(1, 0x00, (0x474154,)), "0009 81 00000001 00 474154"),
    (ReadResponse(4, 0x00, (0x173044,)), "0009 81 00000004 00 173044"),
    (ReadResponse(5, 0x00, (0x000003, 0x000005)), "000c 81 00000005 00 000003 000005"),
]


@pytest.mark.parametrize(("request_", "wire"), REQUEST_VECTORS)
def test_request_roundtrip(request_, wire):
    assert encode_request(request_) == h(wire)
    assert decode_request(h(wire)) == request_


@pytest.mark.parametrize(("response", "wire"), RESPONSE_VECTORS)
def test_response_roundtrip(response, wire):
    assert encode_response(response) == h(wire)
    assert decode_response(h(wire)) == response


def test_complete_request_frame_from_appendix_b():
    frame = h(
        "00 0f c9 1d 98 f2 50 7b 9d 42 d0 00 61 20 00 06"
        "01 00 00 00 06 ff 01 00 6c 35 00 03 00 00 00 00"
    ).ljust(64, b"\x00")
    message = pad(encode_request(Read(6, (ReadCommand(Space.X, 0x006C35),))), REQUEST_MIN_LEN)
    assert frame[14:] == message
    assert len(frame) == 64


def test_padding_is_ignored_when_decoding():
    request = Read(3, (ReadCommand(Space.X, 0x006C33),))
    assert decode_request(pad(encode_request(request), REQUEST_MIN_LEN)) == request

    response = ConnectResponse(1, 2)
    assert decode_response(pad(encode_response(response), RESPONSE_MIN_LEN)) == response


def test_pad_keeps_longer_messages():
    request = Read(1, tuple(ReadCommand(Space.X, a) for a in ID_BLOCK * 2))
    message = encode_request(request)
    assert len(message) > REQUEST_MIN_LEN
    assert pad(message, REQUEST_MIN_LEN) == message


def test_read_with_64_commands():
    request = Read(9, tuple(ReadCommand(Space.X, 0x007000 + i) for i in range(64)))
    message = encode_request(request)
    assert len(message) == 8 + 6 * 64
    assert decode_request(message) == request

    response = ReadResponse(9, 0x00, tuple(range(64)))
    message = encode_response(response)
    assert message[:2] == (6 + 3 * 64).to_bytes(2, "big")
    assert decode_response(message) == response


def test_error_response_without_words():
    response = ReadResponse(2, 0x01)
    assert encode_response(response) == h("0006 81 00000002 01")
    assert decode_response(h("0006 81 00000002 01")) == response


@pytest.mark.parametrize(
    ("wire", "error"),
    [
        ("0006 01 000001", "shorter than the header"),
        ("0006 01 00000001 00 01 006c36 0003", "request status"),
        ("0006 01 00000001 ff 01 006c36", "exceeds message"),
        ("0000 01 00000001 ff", "READ with Length 0"),
        ("0005 01 00000001 ff 01 006c36 00", "READ with Length 5"),
        ("0008 31 00000001 ff 00000000 00000000", "stage 1 marker"),
        ("0004 31 00000001 ff 6e6f6962", "stage 2 key"),
        ("0006 31 00000001 ff 6e6f69610000", "CONNECT with Length 6"),
        ("0004 50 00000001 ff 00000000", "DISCONNECT with Length 4"),
        ("0000 02 00000001 ff", "unknown request type 0x02"),
        # Legacy short format (5.6): the bytes after the control byte do not form a
        # valid header.
        ("0007 01 6c36 000000 4f22", "request status"),
    ],
)
def test_malformed_requests(wire, error):
    with pytest.raises(ProtocolError, match=error):
        decode_request(h(wire))


@pytest.mark.parametrize(
    ("wire", "error"),
    [
        ("0005 81 00000001 00", "below header size"),
        ("0009 81 00000001 00 4741", "exceeds message"),
        ("0008 81 00000001 00 4741", "payload of 2 bytes"),
        ("000e b1 00000001 e0 00000002 95743927", "CONNECT magic"),
        ("000a b1 00000001 e0 00000002", "too short"),
        ("0006 b1 00000001 00", "CONNECT response status"),
        ("0006 82 00000001 00", "unknown response type 0x82"),
    ],
)
def test_malformed_responses(wire, error):
    with pytest.raises(ProtocolError, match=error):
        decode_response(h(wire))


def test_values_must_fit_into_24_bits():
    with pytest.raises(ValueError, match="address"):
        encode_request(Read(1, (ReadCommand(Space.X, 0x1000000),)))
    with pytest.raises(ValueError, match="word"):
        encode_response(ReadResponse(1, 0x00, (0x1000000,)))
