"""Command line interface: runs a simulated modem on a network interface."""

from __future__ import annotations

import argparse
import logging
import signal
import threading

from .device import FIRMWARE_750202, FIRMWARE_BRANCH_161, FIRMWARE_UNKNOWN, LineState, Role
from .modem import Modem
from .transport import Transport

log = logging.getLogger("mt5311sim")

FIRMWARES = {
    "750202": FIRMWARE_750202,
    "1.61": FIRMWARE_BRANCH_161,
    "unknown": FIRMWARE_UNKNOWN,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mt5311sim",
        description="Simulate an MT5311 VDSL2 SFP modem on a network interface "
                    "(needs CAP_NET_RAW).")
    parser.add_argument("--interface", "-i", required=True,
                        help="interface the simulated modem is attached to")
    parser.add_argument("--firmware", choices=FIRMWARES, default="750202",
                        help="firmware build: 750202 (layout 1.60), 1.61, or an unknown "
                             "layout (default: %(default)s)")
    parser.add_argument("--role", choices=["rt", "ot"], default="rt",
                        help="customer side (rt) or network side (ot) (default: %(default)s)")
    parser.add_argument("--state", choices=[s.name.lower() for s in LineState],
                        default="showtime", help="line state (default: %(default)s)")
    parser.add_argument("--verbose", "-v", action="store_true", help="log every message")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s: %(message)s")

    modem = Modem(FIRMWARES[args.firmware], Role.RT if args.role == "rt" else Role.OT)
    modem.line.set_state(LineState[args.state.upper()])

    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())

    with Transport(modem, args.interface) as transport:
        log.info("simulating modem %s on %s", transport.mac.hex(":"), args.interface)
        while not stop.wait(1):
            modem.line.tick()
        log.info("stopped")


if __name__ == "__main__":
    main()
