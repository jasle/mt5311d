import pytest

from mt5311sim import words


def test_unsigned():
    assert words.unsigned(0) == 0
    assert words.unsigned(0xFFFFFF) == 0xFFFFFF
    for value in (-1, 0x1000000):
        with pytest.raises(ValueError):
            words.unsigned(value)


@pytest.mark.parametrize(
    ("value", "word"),
    [(0, 0x000000), (128, 0x000080), (-29, 0xFFFFE3), (-52, 0xFFFFCC),
     (0x7FFFFF, 0x7FFFFF), (-0x800000, 0x800000)],
)
def test_signed(value, word):
    assert words.signed(value) == word


def test_signed_range():
    for value in (0x800000, -0x800001):
        with pytest.raises(ValueError):
            words.signed(value)


def test_counter_wraps_at_2_pow_24():
    assert words.counter(0xFFFFFF) == 0xFFFFFF
    assert words.counter(0x1000000) == 0
    assert words.counter(0x1000005) == 5
    with pytest.raises(ValueError):
        words.counter(-1)


def test_scaled_matches_observed_values():
    # Observed values from spec section 9.1.
    assert words.scaled(3.3, 0.1, is_signed=True) == 0x000021
    assert words.scaled(25.1, 0.1) == 0x0000FB
    assert words.scaled(12.8, 0.1, is_signed=True) == 0x000080
    assert words.scaled(-2.9, 0.1, is_signed=True) == 0xFFFFE3
    with pytest.raises(ValueError):
        words.scaled(-0.1, 0.1)


def test_bcd():
    assert words.bcd("090718") == 0x090718
    assert words.bcd("173044") == 0x173044
    for digits in ("9718", "0907a8"):
        with pytest.raises(ValueError):
            words.bcd(digits)


def test_octets():
    assert words.octets(b"GAT", 1) == [0x474154]
    # Vendor ID observed on an RT device (9.2.5).
    assert words.octets(bytes.fromhex("b500424443 4d1cc0"), 3) == [0xB50042, 0x44434D, 0x1CC000]
    assert words.octets(b"", 2) == [0, 0]
    with pytest.raises(ValueError):
        words.octets(b"abcd", 1)
