# mt5311d

Daemon for OpenWrt to read line diagnostics from MT5311 based VDSL2 SFP modems and
expose them on ubus.

mt5311d talks to the modem over its Ethernet management protocol (EBM) and provides
the line status as ubus object `dsl` with the methods `metrics` and `statistics`, in
the format of the Lantiq DSL daemon. The LuCI DSL status and the Prometheus and
collectd DSL exporters therefore work without changes. Only modems running as the
customer side (RT) are supported.

## Status

mt5311d runs as a service on a router with OpenWrt 25.12.5 and an MT5311 with
firmware 750202 on a VDSL2 17a line; the LuCI DSL status and the xDSL statistics page
show its data. It is based on the protocol specification
[`MT5311_EBM_Monitoring_Spec.md`](MT5311_EBM_Monitoring_Spec.md). The modem simulator
for development and tests is in [`sim/`](sim/README.md).

## Limitations

- Only modems running as the customer side (RT) are supported; a modem running as the
  network side (OT) is reported as not supported.
- Only firmware with the address layouts of branches 1.60 and 1.61 is supported (see
  the specification, section 8); other firmware is reported as not supported.
- There is no per-tone data (bits, SNR, QLN, Hlog): `statistics` has the band limits,
  but the LuCI spectrum page shows empty charts.
- `metrics` leaves out what the modem does not provide or what is not reliable, e.g.
  the upstream attenuation (`latn`, `satn`), vectoring, bitswap, retransmission
  (G.INP), `errors.near.loss` and the far-end counters other than `cv_c` and `fec_c`.
- The error counters count since the start of the modem and are extended beyond the
  modem's 24 bits; after the session with the modem is lost they start again from the
  modem's values.
- Delay and INP read 0 on a line without interleaving; with retransmission their
  meaning is not confirmed (specification, Appendix C).

## Installation

mt5311d needs OpenWrt 25.12 or newer. It is packaged by a Makefile in a package feed
that fetches this repository; the files go to these places:

| Repository | Router |
|---|---|
| `src/mt5311d.uc` | `/usr/sbin/mt5311d` |
| `src/mt5311d/*.uc` | `/usr/share/ucode/mt5311d/` |
| `files/mt5311d.init` | `/etc/init.d/mt5311d` |
| `files/mt5311d.config` | `/etc/config/mt5311d` |

Example feed Makefile:

```make
include $(TOPDIR)/rules.mk

PKG_NAME:=mt5311d
PKG_VERSION:=0.2.0
PKG_RELEASE:=1

PKG_SOURCE:=$(PKG_NAME)-$(PKG_VERSION).tar.gz
PKG_SOURCE_URL:=https://codeload.github.com/jasle/$(PKG_NAME)/tar.gz/$(PKG_VERSION)?
PKG_HASH:=<from make package/mt5311d/check FIXUP=1>

PKG_MAINTAINER:=jasle <jasle@riseup.net>
PKG_LICENSE:=GPL-3.0-or-later
PKG_LICENSE_FILES:=LICENSE

include $(INCLUDE_DIR)/package.mk

define Package/mt5311d
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Line status of Metanoia MT5311 VDSL2 SFP modems on ubus
  DEPENDS:=+ucode +ucode-mod-fs +ucode-mod-log +ucode-mod-socket \
    +ucode-mod-struct +ucode-mod-ubus +ucode-mod-uci +ucode-mod-uloop
  PKGARCH:=all
endef

define Package/mt5311d/description
  Provides the line status of a Metanoia MT5311 VDSL2 SFP modem as ubus
  object "dsl" in the format of the Lantiq DSL daemon.
endef

define Package/mt5311d/conffiles
/etc/config/mt5311d
endef

define Build/Compile
endef

define Package/mt5311d/install
	$(INSTALL_DIR) $(1)/usr/sbin $(1)/usr/share/ucode/mt5311d $(1)/etc/init.d $(1)/etc/config
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/src/mt5311d.uc $(1)/usr/sbin/mt5311d
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/src/mt5311d/*.uc $(1)/usr/share/ucode/mt5311d/
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/files/mt5311d.init $(1)/etc/init.d/mt5311d
	$(INSTALL_CONF) $(PKG_BUILD_DIR)/files/mt5311d.config $(1)/etc/config/mt5311d
endef

$(eval $(call BuildPackage,mt5311d))
```

For local changes, OpenWrt's `CONFIG_SRC_TREE_OVERRIDE` builds from a working copy
linked as `git-src` in the package directory.

## Configuration

Set the interface of the SFP modem and the modem's MAC address, then enable the
service:

```sh
uci set mt5311d.main.interface='sfp1'
uci set mt5311d.main.macaddr='00:0f:c9:1d:98:f2'
uci set mt5311d.main.enabled='1'
uci commit mt5311d
/etc/init.d/mt5311d enable
/etc/init.d/mt5311d start
```

| Option | Default | Meaning |
|---|---|---|
| `enabled` | `0` | start the service |
| `interface` | | network interface the modem is attached to |
| `macaddr` | | MAC address of the modem |
| `interval` | `30` | seconds between background poll cycles |
| `max_age` | `5` | seconds during which ubus calls get the last state |

The modem is read on every ubus call unless the last state is younger than `max_age`,
and in the background every `interval` seconds, so that counter overflows and
retrains are noticed. Messages go to the system log (`logread -e mt5311d`).

```sh
ubus call dsl metrics
ubus call dsl statistics
```

LuCI shows its DSL status only if `/etc/board.json` has a DSL modem entry. mt5311d adds
such an entry while it reaches a supported modem and removes it when the service
stops; an entry of a board with a built-in modem is left alone.

## Diagnostics

`mt5311d -v` prints the installed version, `mt5311d -h` the command line options.

[`tools/mt5311-probe.uc`](tools/mt5311-probe.uc) reads a modem once and prints the
firmware, the selected address layout and all values mt5311d knows as JSON. It only
sends CONNECT and READ requests. On a router with `ucode-mod-socket`,
`ucode-mod-struct` and `ucode-mod-uloop`:

```sh
scp -O -r src tools root@router:/tmp/mt5311d/
ssh root@router "ucode -L '/tmp/mt5311d/src/*.uc' /tmp/mt5311d/tools/mt5311-probe.uc <interface> <modem-mac>"
```

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

To release, raise `VERSION` in [`src/mt5311d.uc`](src/mt5311d.uc), commit, tag the
commit with `task tag` (the tag is the version, e.g. `0.2.0`) and push the branch and
the tag. The package Makefile's `PKG_VERSION` is this tag.

## License

GPL-3.0, see [LICENSE](LICENSE).
