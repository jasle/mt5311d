"""EBM message format (spec sections 4 and 5).

All functions work on the EBM message, i.e. the Ethernet payload after the
EtherType. Ethernet addressing is the job of the transport.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

ETHERTYPE = 0x6120

HEADER = struct.Struct(">HBIB")  # Length, Type, Sequence, Status
HEADER_LEN = HEADER.size

RESPONSE_BIT = 0x80
STATUS_REQUEST = 0xFF

# Minimum message sizes so that frames reach 64 bytes (requests, 4.1) and the
# Ethernet minimum of 60 bytes (responses), both without FCS.
REQUEST_MIN_LEN = 64 - 14
RESPONSE_MIN_LEN = 60 - 14

CONNECT_STAGE1_MARKER = 0xFFFFFFFF
CONNECT_STAGE1_VALUE = 0x00000002
CONNECT_MAGIC = 0x95743926
CONNECT_STAGE2_KEY = b"noia"

WORD_BYTES = 3
READ_COMMAND = struct.Struct(">BBHH")  # Space, Address (3 bytes), Count
MAX_WORD = 0xFFFFFF


class MsgType(IntEnum):
    READ = 0x01
    CONNECT = 0x31
    DISCONNECT = 0x50


class Status(IntEnum):
    OK = 0x00
    CONNECT_STAGE1 = 0xE0
    CONNECT_STAGE2 = 0xE1


class Space(IntEnum):
    X = 1
    Y = 2
    P = 3


class ProtocolError(ValueError):
    """A message does not follow the EBM format."""


# Requests


@dataclass(frozen=True)
class ConnectStage1:
    seq: int
    parameter: int = 0


@dataclass(frozen=True)
class ConnectStage2:
    seq: int


@dataclass(frozen=True)
class ReadCommand:
    space: int
    address: int
    count: int = WORD_BYTES


@dataclass(frozen=True)
class Read:
    seq: int
    commands: tuple[ReadCommand, ...]


@dataclass(frozen=True)
class Disconnect:
    seq: int


Request = ConnectStage1 | ConnectStage2 | Read | Disconnect


# Responses


@dataclass(frozen=True)
class ConnectResponse:
    seq: int
    stage: int


@dataclass(frozen=True)
class ReadResponse:
    seq: int
    status: int = Status.OK
    words: tuple[int, ...] = ()


Response = ConnectResponse | ReadResponse


def pad(message: bytes, min_len: int) -> bytes:
    """Pads a message with zero bytes to min_len."""
    return message.ljust(min_len, b"\x00")


def _header(length: int, msg_type: int, seq: int, status: int) -> bytes:
    return HEADER.pack(length, msg_type, seq, status)


def encode_request(request: Request) -> bytes:
    """Encodes a request without padding (4.3: Length counts the payload)."""
    match request:
        case ConnectStage1(seq, parameter):
            payload = struct.pack(">II", CONNECT_STAGE1_MARKER, parameter)
            msg_type = MsgType.CONNECT
        case ConnectStage2(seq):
            payload = CONNECT_STAGE2_KEY
            msg_type = MsgType.CONNECT
        case Read(seq, commands):
            payload = b"".join(_encode_command(c) for c in commands)
            msg_type = MsgType.READ
        case Disconnect(seq):
            payload = b""
            msg_type = MsgType.DISCONNECT
        case _:
            raise TypeError(f"not a request: {request!r}")

    return _header(len(payload), msg_type, seq, STATUS_REQUEST) + payload


def decode_request(message: bytes) -> Request:
    """Decodes a request; bytes after the Length field are padding and ignored."""
    length, msg_type, seq, status = _unpack_header(message)
    if status != STATUS_REQUEST:
        raise ProtocolError(f"request status 0x{status:02x}, expected 0xff")

    payload = message[HEADER_LEN : HEADER_LEN + length]
    if len(payload) < length:
        raise ProtocolError(f"Length {length} exceeds message")

    match msg_type:
        case MsgType.CONNECT if length == 8:
            marker, parameter = struct.unpack(">II", payload)
            if marker != CONNECT_STAGE1_MARKER:
                raise ProtocolError(f"CONNECT stage 1 marker 0x{marker:08x}")
            return ConnectStage1(seq, parameter)
        case MsgType.CONNECT if length == 4:
            if payload != CONNECT_STAGE2_KEY:
                raise ProtocolError(f"CONNECT stage 2 key {payload!r}")
            return ConnectStage2(seq)
        case MsgType.CONNECT:
            raise ProtocolError(f"CONNECT with Length {length}")
        case MsgType.READ:
            if length == 0 or length % READ_COMMAND.size:
                raise ProtocolError(f"READ with Length {length}")
            commands = tuple(
                ReadCommand(space, (hi << 16) | lo, count)
                for space, hi, lo, count in READ_COMMAND.iter_unpack(payload)
            )
            return Read(seq, commands)
        case MsgType.DISCONNECT if length == 0:
            return Disconnect(seq)
        case MsgType.DISCONNECT:
            raise ProtocolError(f"DISCONNECT with Length {length}")
        case _:
            raise ProtocolError(f"unknown request type 0x{msg_type:02x}")


def encode_response(response: Response) -> bytes:
    """Encodes a response without padding (4.3: Length is 6 plus the payload)."""
    match response:
        case ConnectResponse(seq, 1):
            msg_type, status = MsgType.CONNECT, Status.CONNECT_STAGE1
            payload = struct.pack(">II", CONNECT_STAGE1_VALUE, CONNECT_MAGIC)
        case ConnectResponse(seq, 2):
            msg_type, status = MsgType.CONNECT, Status.CONNECT_STAGE2
            payload = bytes(6)
        case ConnectResponse(seq, stage):
            raise ValueError(f"invalid CONNECT stage {stage}")
        case ReadResponse(seq, status, words):
            msg_type = MsgType.READ
            payload = b"".join(_encode_word(w) for w in words)
        case _:
            raise TypeError(f"not a response: {response!r}")

    length = HEADER_LEN - 2 + len(payload)
    return _header(length, msg_type | RESPONSE_BIT, seq, status) + payload


def decode_response(message: bytes) -> Response:
    """Decodes a response; bytes after the Length field are padding and ignored."""
    length, msg_type, seq, status = _unpack_header(message)
    if length < HEADER_LEN - 2:
        raise ProtocolError(f"response Length {length} below header size")

    payload = message[HEADER_LEN : 2 + length]
    if len(payload) < length - (HEADER_LEN - 2):
        raise ProtocolError(f"Length {length} exceeds message")

    if msg_type == MsgType.CONNECT | RESPONSE_BIT:
        if status == Status.CONNECT_STAGE1:
            if len(payload) < 8:
                raise ProtocolError("CONNECT stage 1 response too short")
            _value, magic = struct.unpack_from(">II", payload)
            if magic != CONNECT_MAGIC:
                raise ProtocolError(f"CONNECT magic 0x{magic:08x}")
            return ConnectResponse(seq, 1)
        if status == Status.CONNECT_STAGE2:
            return ConnectResponse(seq, 2)
        raise ProtocolError(f"CONNECT response status 0x{status:02x}")

    if msg_type == MsgType.READ | RESPONSE_BIT:
        if len(payload) % WORD_BYTES:
            raise ProtocolError(f"READ response payload of {len(payload)} bytes")
        words = tuple(
            int.from_bytes(payload[i : i + WORD_BYTES], "big")
            for i in range(0, len(payload), WORD_BYTES)
        )
        return ReadResponse(seq, status, words)

    raise ProtocolError(f"unknown response type 0x{msg_type:02x}")


def _unpack_header(message: bytes) -> tuple[int, int, int, int]:
    if len(message) < HEADER_LEN:
        raise ProtocolError(f"message of {len(message)} bytes is shorter than the header")
    return HEADER.unpack_from(message)


def _encode_command(command: ReadCommand) -> bytes:
    if not 0 <= command.address <= MAX_WORD:
        raise ValueError(f"address 0x{command.address:x} does not fit into 24 bits")
    hi, lo = command.address >> 16, command.address & 0xFFFF
    return READ_COMMAND.pack(command.space, hi, lo, command.count)


def _encode_word(word: int) -> bytes:
    if not 0 <= word <= MAX_WORD:
        raise ValueError(f"word 0x{word:x} does not fit into 24 bits")
    return word.to_bytes(WORD_BYTES, "big")
