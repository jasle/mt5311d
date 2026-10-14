import os
import subprocess

import pytest

# Set by `task sim:test-netns`, which runs pytest in a new network namespace. The
# fixtures below create interfaces and must never run in the host's namespace.
NETNS_ENV = "MT5311SIM_NETNS"


def _ip(*args: str) -> None:
    subprocess.run(["ip", *args], check=True)


@pytest.fixture(scope="session")
def veth():
    """A veth pair (host side, modem side) in the test's network namespace."""
    if os.environ.get(NETNS_ENV) != "1":
        pytest.skip("needs a network namespace, run `task sim:test-netns`")

    host, modem = "ebm-host", "ebm-modem"
    _ip("link", "add", "name", host, "type", "veth", "peer", "name", modem)
    _ip("link", "set", "dev", host, "up")
    _ip("link", "set", "dev", modem, "up")
    yield host, modem
    _ip("link", "del", "dev", host)
