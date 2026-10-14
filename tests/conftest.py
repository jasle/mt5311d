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

from mt5311sim import protocol as sim
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


# Poller driver, shared by the tests of the poller and of the ubus mapping.
# on_cycle(n, action) runs action when the n-th poll cycle starts reading, before
# the modem answers.

# Runs STEPS with a poller and prints the results of the refresh steps:
#   [ 'refresh' ]        -> report(state) of the refresh callback's state
#   [ 'refresh', n ]     -> n refreshes at once; the list of their reports
#   [ 'start' ], [ 'stop' ], [ 'wait', ms ]
# IMPORTS and REPORT are replaced with further imports and the expression that
# turns `state` into the reported value.
POLLER_DRIVER = """
    import * as uloop from 'uloop';
    import * as session from 'mt5311d.session';
    import * as poller from 'mt5311d.poller';
    IMPORTS

    function report(state) {
        return REPORT;
    }

    uloop.init();

    const s = session.create(SESSION);
    const error = s.open();
    if (error)
        die(error);

    const p = poller.create(s, OPTIONS);
    const results = [];
    let i = 0;

    function next() {
        if (i >= length(STEPS)) {
            uloop.end();
            return;
        }

        const step = STEPS[i++];

        if (step[0] == 'refresh' && length(step) == 1)
            p.refresh((state) => { push(results, report(state)); next(); });
        else if (step[0] == 'refresh') {
            const states = [];
            for (let j = 0; j < step[1]; j++)
                p.refresh((state) => {
                    push(states, report(state));
                    if (length(states) == step[1]) {
                        push(results, states);
                        next();
                    }
                });
        }
        else if (step[0] == 'start') {
            p.start();
            next();
        }
        else if (step[0] == 'stop') {
            p.stop();
            next();
        }
        else
            uloop.timer(step[1], next);
    }

    uloop.timer(WATCHDOG, () => die('test driver timed out'));
    next();
    uloop.run();
    s.close();
    printf('%J', results);
"""

ID_START = 0x006C31
MAX_COMMANDS = 64


@pytest.fixture
def run_poller(ucode, simulator):
    """Runs a poller against the simulator; returns the reports of its refreshes.

    imports and report change what is reported for a state (see POLLER_DRIVER).
    """

    def run_poller(*steps, mac=None, watchdog=10000, imports="", report="state",
                   **options):
        options.setdefault("reconnect_delay", 100)
        options.setdefault("max_age", 0)
        source = POLLER_DRIVER.replace("IMPORTS", imports).replace("REPORT", report)
        return ucode.run(source, SESSION={"interface": DAEMON_INTERFACE,
                                          "mac": mac or simulator.mac},
                         OPTIONS=options, STEPS=list(steps), WATCHDOG=watchdog)

    return run_poller


@pytest.fixture
def on_cycle(simulator):
    """Runs action when the n-th poll cycle (counted from 1) starts reading."""
    cycles = 0
    actions = {}

    # A poll cycle starts with a full READ that begins with the identification
    # block; the READ of the layout selection has only 20 commands.
    def hook(received):
        nonlocal cycles
        request = received.request
        if (isinstance(request, sim.Read) and request.commands[0].address == ID_START
                and len(request.commands) == MAX_COMMANDS):
            cycles += 1
            if cycles in actions:
                actions[cycles]()

    simulator.modem.on_request(hook)

    def on_cycle(n, action):
        actions[n] = action

    return on_cycle
