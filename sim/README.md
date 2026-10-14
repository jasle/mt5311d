# mt5311sim

Simulator for the EBM monitoring protocol of Metanoia MT5311 VDSL2 SFP modems, as
described in [`../MT5311_EBM_Monitoring_Spec.md`](../MT5311_EBM_Monitoring_Spec.md).
It is used to develop and test mt5311d without a modem.

The simulated modem answers CONNECT, READ and DISCONNECT over raw Ethernet frames
(EtherType `0x6120`) from a simulated DSP memory. It holds the registers mt5311d
needs in the address layouts of firmware branch 1.60 and 1.61, and a line model
that writes line state, showtime values and counters in the encodings of the
specification. Faults such as lost, late or error responses can be injected.

## Setup

Needs Python 3.12 or newer and [Poetry](https://python-poetry.org/).

```sh
task sim:install
```

## Tests

```sh
task sim:test         # tests that need no network interfaces
task sim:test-netns   # all tests, including real frames over a veth pair
```

`task sim:test-netns` runs pytest in a new user and network namespace
(`unshare --map-root-user --net`), so it needs no root privileges and does not
touch the host's interfaces.

## Running the simulator

```sh
task sim:run -- --interface veth1 [--firmware 750202|1.61|unknown]
                [--role rt|ot] [--state idle|handshake|training|showtime] [-v]
```

The simulator uses the MAC address of the interface as the modem's address and
needs `CAP_NET_RAW`, e.g. inside a network namespace created with `unshare`.

## Use from Python

```python
from mt5311sim.modem import Modem
from mt5311sim.transport import Transport

modem = Modem()
with Transport(modem, "veth1"):
    modem.line.showtime()                     # line values from modem.line.status
    modem.line.error_rates["ds"].crc = 2      # CRC errors per second
    modem.line.tick(10)                       # advance time by 10 s
    modem.faults.drop()                       # lose the next response
    modem.reboot()                            # session, line state and counters lost
```
