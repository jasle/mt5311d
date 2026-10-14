# mt5311d

Daemon for OpenWrt to read line diagnostics from MT5311 based VDSL2 SFP modems and
expose them on ubus.

## Status

The daemon is being implemented; its ucode modules are in [`src/`](src/). It is based
on the protocol specification
[`MT5311_EBM_Monitoring_Spec.md`](MT5311_EBM_Monitoring_Spec.md). A modem simulator for
development and tests is in [`sim/`](sim/README.md).

## Development

The daemon is written in [ucode](https://github.com/jow-/ucode). Its tests run with
pytest on the development machine; the ucode code itself runs in a container with the
OpenWrt 25.12.5 userland ([`tests/container/Containerfile`](tests/container/Containerfile)),
so it is tested with the same ucode, uloop and ubus as on a router. pytest manages the
container with [testcontainers](https://testcontainers-python.readthedocs.io/) on
rootless Podman.

Requirements: Python 3.12 or newer, [Poetry](https://python-poetry.org/),
[Task](https://taskfile.dev/) and rootless [Podman](https://podman.io/) with its API
socket enabled once:

```sh
systemctl --user enable --now podman.socket
```

```sh
task install   # test dependencies and the simulator
task test      # builds the test image on the first run
task check     # syntax check of all ucode sources
```

## License

GPL-3.0, see [LICENSE](LICENSE).
