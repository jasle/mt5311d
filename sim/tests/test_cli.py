import pytest

from mt5311sim.__main__ import FIRMWARES, parse_args
from mt5311sim.device import FIRMWARE_750202


def test_defaults():
    args = parse_args(["-i", "veth1"])
    assert args.interface == "veth1"
    assert FIRMWARES[args.firmware] is FIRMWARE_750202
    assert args.role == "rt"
    assert args.state == "showtime"


def test_options():
    args = parse_args(["--interface", "sfp1", "--firmware", "1.61", "--role", "ot",
                       "--state", "training", "-v"])
    assert (args.firmware, args.role, args.state, args.verbose) == ("1.61", "ot",
                                                                    "training", True)


@pytest.mark.parametrize("argv", [[], ["-i", "x", "--state", "up"], ["-i", "x", "--firmware", "1"]])
def test_invalid_arguments(argv):
    with pytest.raises(SystemExit):
        parse_args(argv)
