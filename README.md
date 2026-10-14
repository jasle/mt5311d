# mt5311d

Daemon for OpenWrt to read line diagnostics from MT5311 based VDSL2 SFP modems and
expose them on ubus.

## Status

The daemon is being implemented; its ucode modules are in [`src/`](src/). It is based
on the protocol specification
[`MT5311_EBM_Monitoring_Spec.md`](MT5311_EBM_Monitoring_Spec.md). A modem simulator for
development and tests is in [`sim/`](sim/README.md).

## Development

The daemon is written in [ucode](https://github.com/jow-/ucode). Its tests run on the
development machine with pytest, which executes the ucode code with the local ucode
interpreter.

Requirements: ucode (set `UCODE` if it is not on the `PATH`), Python 3.11 or newer,
[Poetry](https://python-poetry.org/) and [Task](https://taskfile.dev/).

```sh
task install   # test dependencies and the simulator
task test
task check     # syntax check of all ucode sources
```

## License

GPL-3.0, see [LICENSE](LICENSE).
