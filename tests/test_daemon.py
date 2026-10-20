"""Tests of the daemon src/mt5311d.uc with ubusd in the container.

Every scenario runs in a single exec: a shell script starts ubusd and the
daemon, waits for the ubus object, makes the calls, stops the daemon with
SIGTERM and stops ubusd, so that nothing keeps running in the container.
"""

import json
import re
import shlex
import uuid
from pathlib import Path

import pytest

from conftest import DAEMON_INTERFACE
from ucode import CONTAINER_REPO

DAEMON = f"{CONTAINER_REPO}/src/mt5311d.uc"
NETWORK = {"model": {"id": "test,board", "name": "Test"}}

# The version as written in the source, which a release tag has to match.
VERSION = re.search(r"^const VERSION = '([^']+)';$",
                    (Path(__file__).parent.parent / "src/mt5311d.uc").read_text(),
                    re.MULTILINE)[1]

# The options with which the generic tests of the openwrt/packages CI look for
# the package version in the output of every executable, in their order.
CI_VERSION_OPTIONS = ("--version", "-version", "version", "-v", "-V", "--help", "-help", "-?")


def uci_config(**options):
    lines = ["config mt5311d 'main'"]
    lines += [f"\toption {name} '{value}'" for name, value in options.items()]
    return "\n".join(lines) + "\n"


@pytest.fixture
def run_daemon(execute):
    """Runs the daemon with a configuration and board.json, makes ubus calls.

    calls are method names or (method, message) pairs. Returns a dict with the
    output of each call ("call:<method>"), the board file
    while running and after the stop, the exit code and the log.
    """
    directory = f"/tmp/daemon-{uuid.uuid4().hex[:8]}"

    def run_daemon(config, board, calls=("metrics",), wait_for_object=True):
        sock = f"{directory}/ubus.sock"
        board_path = f"{directory}/board.json"
        steps = []
        for call in calls:
            name, message = (call, "") if isinstance(call, str) else call
            steps.append(f"echo '=== call:{name}'; ubus -s {sock} -t 10 call dsl {name} "
                         f"{shlex.quote(json.dumps(message)) if message else ''}")
        script = f"""
            rm -rf {directory}; mkdir -p {directory}/config
            printf '%s' {shlex.quote(config)} > {directory}/config/mt5311d
            printf '%s' {shlex.quote(json.dumps(board))} > {board_path}
            ubusd -s {sock} & UBUSD=$!
            while [ ! -S {sock} ]; do sleep 1; done
            ucode -L '{CONTAINER_REPO}/src/*.uc' {DAEMON} -c {directory}/config \\
                -s {sock} -b {board_path} -f 2> {directory}/log & DAEMON=$!
            if {'true' if wait_for_object else 'false'}; then
                ubus -s {sock} -t 10 wait_for dsl
                {'; '.join(steps)}
                echo '=== board:running'; cat {board_path}; echo
                kill -TERM $DAEMON
            fi
            wait $DAEMON; CODE=$?; echo "=== exit"; echo $CODE
            echo '=== board:stopped'; cat {board_path}; echo
            echo '=== log'; cat {directory}/log
            kill $UBUSD; wait $UBUSD 2>/dev/null
        """
        returncode, stdout, stderr = execute(["sh", "-c", script])
        assert returncode == 0, stderr

        sections = {}
        for part in stdout.split("=== ")[1:]:
            name, _, body = part.partition("\n")
            sections[name] = body.strip()

        result = {"exit": int(sections["exit"]), "log": sections["log"]}
        for name, body in sections.items():
            if name.startswith(("call:", "board:")):
                result[name] = json.loads(body) if body else None
        return result

    return run_daemon


def config_for(simulator, **options):
    return uci_config(interface=DAEMON_INTERFACE, macaddr=simulator.mac, **options)


def test_metrics_and_statistics(run_daemon, simulator):
    line = simulator.modem.line
    line.showtime()
    line.tick(100)
    result = run_daemon(config_for(simulator), NETWORK, calls=("metrics", "statistics"))

    metrics = result["call:metrics"]
    assert metrics["state"] == "Showtime with TC-Layer sync"
    assert metrics["up"] is True
    assert metrics["uptime"] == 100
    assert metrics["driver_version"] == f"mt5311d {VERSION}"
    assert metrics["downstream"]["data_rate"] == line.status.downstream.data_rate * 1000
    assert result["call:statistics"]["bands"]["downstream"]["limits"][0] == {
        "first": line.status.downstream.tones[0][0],
        "last": line.status.downstream.tones[0][1],
    }
    assert result["exit"] == 0
    assert "address layout 1.60" in result["log"]


def test_calls_through_uhttpd(run_daemon, simulator):
    # uhttpd adds the session ID of LuCI to the arguments of every call.
    session = {"ubus_rpc_session": "0123456789abcdef0123456789abcdef"}
    result = run_daemon(config_for(simulator), NETWORK,
                        calls=(("metrics", session), ("statistics", session)))
    assert result["call:metrics"]["chipset"] == "Metanoia MT5311"
    assert "bands" in result["call:statistics"]


def test_board_entry_while_running(run_daemon, simulator):
    result = run_daemon(config_for(simulator), NETWORK)
    assert result["board:running"] == {
        **NETWORK, "dsl": {"modem": {"type": "vdsl", "managed_by": "mt5311d"}},
    }
    assert result["board:stopped"] == NETWORK


def test_foreign_board_entry_is_kept(run_daemon, simulator):
    board = {**NETWORK, "dsl": {"modem": {"type": "vdsl", "annex": "b"}}}
    result = run_daemon(config_for(simulator), board)
    assert result["board:running"] == board
    assert result["board:stopped"] == board
    assert "DSL modem entry of the board" in result["log"]


def test_modem_not_reachable(run_daemon, simulator):
    config = uci_config(interface=DAEMON_INTERFACE, macaddr="02:00:00:00:00:99")
    result = run_daemon(config, NETWORK)
    metrics = result["call:metrics"]
    assert (metrics["state"], metrics["up"]) == ("Not initialized", False)
    assert result["board:running"] == NETWORK
    assert "no response to CONNECT stage 1" in result["log"]


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"interface": DAEMON_INTERFACE}, "option macaddr is not a MAC address"),
        ({"macaddr": "02:00:00:00:00:01"}, "option interface is missing"),
        ({"interface": DAEMON_INTERFACE, "macaddr": "02:00:00:00:00:01", "interval": "x"},
         "must be numbers of seconds"),
    ],
)
def test_invalid_configuration(run_daemon, options, message):
    result = run_daemon(uci_config(**options), NETWORK, wait_for_object=False)
    assert result["exit"] == 1
    assert message in result["log"]
    assert result["board:stopped"] == NETWORK


def test_missing_configuration(run_daemon):
    result = run_daemon("", NETWORK, wait_for_object=False)
    assert result["exit"] == 1
    assert "section mt5311d.main is missing" in result["log"]


@pytest.fixture
def run_options(execute):
    """Runs the daemon with command line options only; returns exit code, stdout, stderr."""
    def run_options(*options):
        return execute(["ucode", "-L", f"{CONTAINER_REPO}/src/*.uc", DAEMON, *options])

    return run_options


def test_version(run_options):
    assert run_options("-v") == (0, f"mt5311d {VERSION}\n", "")


def test_help(run_options):
    returncode, stdout, stderr = run_options("-h")
    assert (returncode, stderr) == (0, "")
    assert stdout.startswith("usage: mt5311d ")


@pytest.mark.parametrize("options", [("-x",), ("-c",), ("version",)])
def test_invalid_options(run_options, options):
    returncode, stdout, stderr = run_options(*options)
    assert (returncode, stdout) == (1, "")
    assert stderr.startswith("usage: mt5311d ")


def test_ci_version_check(run_options):
    # Every option ends at once, before reading a configuration, and one of them
    # prints the version.
    outputs = []
    for option in CI_VERSION_OPTIONS:
        returncode, stdout, stderr = run_options(option)
        assert returncode in (0, 1), option
        outputs.append(stdout + stderr)
    assert any(VERSION in output for output in outputs)
