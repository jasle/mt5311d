"""Encoding of values into 24-bit DSP words (spec section 7)."""

from __future__ import annotations

WORD_BITS = 24
WORD_MASK = (1 << WORD_BITS) - 1
WORD_BYTES = 3

# Special values (7.3).
NOT_AVAILABLE = 0x7FFFFF
NOT_APPLICABLE = 0x7FFFFE
NOT_INITIALISED = 0xC69A53
INVALID = 0xFFFFCC
OUT_OF_RANGE = 0x19979F


def unsigned(value: int) -> int:
    """Encodes an unsigned integer (Unsigned32, Counter32, Gauge32)."""
    if not 0 <= value <= WORD_MASK:
        raise ValueError(f"{value} is not an unsigned 24-bit value")
    return value


def signed(value: int) -> int:
    """Encodes a signed integer as 24-bit two's complement (Integer32)."""
    if not -(1 << (WORD_BITS - 1)) <= value < (1 << (WORD_BITS - 1)):
        raise ValueError(f"{value} is not a signed 24-bit value")
    return value & WORD_MASK


def counter(value: int) -> int:
    """Encodes a counter; counters wrap at 2^24 (7.2)."""
    if value < 0:
        raise ValueError(f"counter value {value} is negative")
    return value & WORD_MASK


def scaled(value: float, step: float, *, is_signed: bool = False) -> int:
    """Encodes a physical value in units of step, e.g. scaled(25.1, 0.1) for 0.1 dB."""
    raw = round(value / step)
    return signed(raw) if is_signed else unsigned(raw)


def bcd(digits: str) -> int:
    """Encodes six decimal digits as BCD, e.g. bcd("090718") for MMDDYY (9.2.3)."""
    if len(digits) != 6 or not digits.isdigit():
        raise ValueError(f"{digits!r} is not six decimal digits")
    return int(digits, 16)


def octets(data: bytes, words: int) -> list[int]:
    """Packs bytes into words, most significant byte first, padded with zero bytes."""
    if len(data) > words * WORD_BYTES:
        raise ValueError(f"{len(data)} bytes do not fit into {words} words")
    data = data.ljust(words * WORD_BYTES, b"\x00")
    return [int.from_bytes(data[i : i + WORD_BYTES], "big") for i in range(0, len(data), WORD_BYTES)]
