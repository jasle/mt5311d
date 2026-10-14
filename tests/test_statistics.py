"""Tests of statistics() in src/mt5311d/metrics.uc: `ubus call dsl statistics`."""

STATISTICS = {
    "imports": "import * as m from 'mt5311d.metrics';",
    "report": "m.statistics(state)",
}

def empty_spectra(groups):
    # groups must not be 0: the LuCI spectrum view loops forever on an empty x axis.
    empty = {"groupsize": 1, "groups": groups, "data": []}
    return {name: {"downstream": empty, "upstream": empty}
            for name in ("bits", "snr", "qln", "hlog")}


def limits(tones):
    return [{"first": first, "last": last} for first, last in tones]


def test_passbands_in_showtime(run_poller, simulator):
    line = simulator.modem.line
    line.showtime()
    (statistics,) = run_poller(["refresh"], **STATISTICS)
    assert statistics == {
        "bands": {
            "downstream": {"limits": limits(line.status.downstream.tones)},
            "upstream": {"limits": limits(line.status.upstream.tones)},
        },
        # The x axis spans up to the highest tone of all passbands.
        **empty_spectra(max(last for _, last in line.status.downstream.tones
                            + line.status.upstream.tones) + 1),
    }


def test_outside_showtime(run_poller, simulator):
    (statistics,) = run_poller(["refresh"], **STATISTICS)
    assert statistics["bands"] == {"downstream": {"limits": []}, "upstream": {"limits": []}}


def test_no_modem(run_poller):
    (statistics,) = run_poller(["refresh"], mac="02:00:00:00:00:99", **STATISTICS)
    assert statistics == {
        "bands": {"downstream": {"limits": []}, "upstream": {"limits": []}},
        **empty_spectra(1),
    }
