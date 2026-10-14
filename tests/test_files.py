"""Tests of files/: the UCI template and the procd init script."""

import shlex

import pytest

from ucode import CONTAINER_REPO

INIT = f"{CONTAINER_REPO}/files/mt5311d.init"
CONFIG = f"{CONTAINER_REPO}/files/mt5311d.config"

# Runs start_service of the init script with the procd functions replaced by
# stubs that print their arguments.
START_SERVICE = """
    set -u
    dir=$(mktemp -d)
    cp {config} "$dir/mt5311d"
    for setting in {settings}; do uci -c "$dir" set "mt5311d.main.$setting"; done
    uci -c "$dir" commit mt5311d
    set +u
    . /lib/functions.sh
    UCI_CONFIG_DIR="$dir"
    procd_open_instance() {{ echo open; }}
    procd_set_param() {{ echo "param $*"; }}
    procd_close_instance() {{ echo close; }}
    . {init}
    start_service
    echo "rc=$?"
"""


@pytest.fixture
def start_service(execute):
    def start_service(*settings):
        script = START_SERVICE.format(config=CONFIG, init=INIT,
                                      settings=" ".join(shlex.quote(s) for s in settings))
        returncode, stdout, stderr = execute(["sh", "-c", script])
        assert returncode == 0, stderr
        return stdout.splitlines(), stderr

    return start_service


def test_init_script_syntax(execute):
    returncode, _, stderr = execute(["sh", "-n", INIT])
    assert returncode == 0, stderr


def test_config_template(execute):
    returncode, stdout, stderr = execute(["sh", "-c", f"mkdir -p /tmp/tpl && cp {CONFIG} "
                                          "/tmp/tpl/mt5311d && uci -c /tmp/tpl show mt5311d"])
    assert returncode == 0, stderr
    assert stdout.splitlines() == [
        "mt5311d.main=mt5311d",
        "mt5311d.main.enabled='0'",
        "mt5311d.main.interval='30'",
        "mt5311d.main.max_age='5'",
    ]


def test_disabled_by_default(start_service):
    lines, _ = start_service()
    assert lines == ["rc=0"]


def test_enabled(start_service):
    lines, _ = start_service("enabled=1", "interface=sfp1", "macaddr=00:0f:c9:1d:98:f2")
    assert lines == [
        "open",
        "param command /usr/sbin/mt5311d",
        "param respawn",
        "param stdout 1",
        "param stderr 1",
        "close",
        "rc=0",
    ]


@pytest.mark.parametrize("settings", [("interface=sfp1",), ("macaddr=00:0f:c9:1d:98:f2",)])
def test_enabled_without_interface_or_mac(start_service, settings):
    lines, stderr = start_service("enabled=1", *settings)
    assert lines == ["rc=1"]
    assert "set mt5311d.main.interface and mt5311d.main.macaddr" in stderr
