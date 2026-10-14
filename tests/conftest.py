"""Fixtures for the OpenWrt test container.

The container runs the OpenWrt 25.12.5 userland (tests/container/Containerfile)
with the repository mounted read-only. Code runs in it only through exec; the
container itself just waits.
"""

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.image import DockerImage

from mt5311sim.modem import Modem
from mt5311sim.transport import Transport
from ucode import CONTAINER_REPO, REPO, Executor, Ucode

CONTAINER_DIR = REPO / "tests" / "container"
IMAGE_TAG = "mt5311d-test:latest"


@pytest.fixture(scope="session")
def test_image() -> Iterator[str]:
    # Keep the image after the run so that podman's layer cache makes the next
    # build cheap.
    with DockerImage(path=CONTAINER_DIR, dockerfile_path="Containerfile", tag=IMAGE_TAG,
                     clean_up=False) as image:
        yield str(image)


@pytest.fixture(scope="session")
def container(test_image) -> Iterator[DockerContainer]:
    container = (
        DockerContainer(test_image)
        .with_command("sleep infinity")
        .with_volume_mapping(str(REPO), str(CONTAINER_REPO), "ro")
        .with_kwargs(network_mode="none", cap_add=["NET_ADMIN", "NET_RAW"], init=True)
    )
    with container:
        yield container


@pytest.fixture(scope="session")
def execute(container) -> Executor:
    """Runs a command in the container: argv -> (exit code, stdout, stderr)."""
    wrapped = container.get_wrapped_container()

    def execute(argv: list[str]) -> tuple[int, str, str]:
        result = wrapped.exec_run(argv, demux=True)
        stdout, stderr = result.output
        return (result.exit_code,
                (stdout or b"").decode(errors="surrogateescape"),
                (stderr or b"").decode(errors="surrogateescape"))

    return execute


@pytest.fixture(scope="session")
def ucode(execute) -> Ucode:
    """Runs ucode in the container with the modules from src/ on the search path."""
    return Ucode(execute)


# Network: a veth pair inside the container. The daemon side stays in the
# container; the simulator, running in pytest, opens its socket on the modem side
# in the container's network namespace (pytest runs in podman's user namespace).

DAEMON_INTERFACE = "ebm0"
MODEM_INTERFACE = "modem0"


@pytest.fixture(scope="session")
def container_netns(container) -> str:
    wrapped = container.get_wrapped_container()
    wrapped.reload()
    return f"/proc/{wrapped.attrs['State']['Pid']}/ns/net"


@pytest.fixture(scope="session")
def network(execute) -> tuple[str, str]:
    """The veth pair (daemon side, modem side) in the container."""
    for argv in (
        ["ip", "link", "add", "name", DAEMON_INTERFACE, "type", "veth",
         "peer", "name", MODEM_INTERFACE],
        ["ip", "link", "set", "dev", DAEMON_INTERFACE, "up"],
        ["ip", "link", "set", "dev", MODEM_INTERFACE, "up"],
    ):
        returncode, _, stderr = execute(argv)
        assert returncode == 0, stderr
    return DAEMON_INTERFACE, MODEM_INTERFACE


@dataclass(frozen=True)
class Simulator:
    modem: Modem
    mac: str  # the modem's MAC address, lower case


@pytest.fixture
def simulator(network, container_netns) -> Iterator[Simulator]:
    """A simulated modem attached to the modem side of the veth pair."""
    modem = Modem()
    with Transport(modem, network[1], netns=container_netns) as transport:
        yield Simulator(modem, transport.mac.hex(":"))
