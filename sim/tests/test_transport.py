import os
import select
import socket
import subprocess
import time

import pytest

from mt5311sim.faults import reads
from mt5311sim.modem import Modem
from mt5311sim.protocol import (
    ETHERTYPE,
    REQUEST_MIN_LEN,
    RESPONSE_MIN_LEN,
    ConnectResponse,
    ConnectStage1,
    ConnectStage2,
    Read,
    ReadCommand,
    ReadResponse,
    Space,
    decode_response,
    encode_request,
    pad,
)
from mt5311sim.transport import Transport

pytestmark = pytest.mark.netns


class Client:
    """A host that talks to the modem over a raw socket."""

    def __init__(self, interface: str, modem_mac: bytes) -> None:
        self.interface = interface
        self.modem_mac = modem_mac
        self.sock = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(ETHERTYPE))
        self.sock.bind((interface, ETHERTYPE))

    def send(self, request) -> None:
        message = pad(encode_request(request), REQUEST_MIN_LEN)
        self.sock.sendto(message, (self.interface, ETHERTYPE, 0, 0, self.modem_mac))

    def receive(self, timeout: float = 1.0) -> bytes | None:
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            if not select.select([self.sock], [], [], left)[0]:
                break
            message, (_, _, pkttype, _, src) = self.sock.recvfrom(1514)
            if pkttype != socket.PACKET_OUTGOING and src == self.modem_mac:
                return message
        return None

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def modem():
    return Modem()


@pytest.fixture
def transport(veth, modem):
    with Transport(modem, veth[1]) as transport:
        yield transport


@pytest.fixture
def client(veth, transport):
    client = Client(veth[0], transport.mac)
    yield client
    client.close()


def roundtrip(client, request):
    client.send(request)
    message = client.receive()
    assert message is not None, f"no response to {request}"
    return message


def connect(client):
    assert decode_response(roundtrip(client, ConnectStage1(1))) == ConnectResponse(1, 1)
    assert decode_response(roundtrip(client, ConnectStage2(1))) == ConnectResponse(1, 2)


def test_connect_and_read(client):
    connect(client)
    message = roundtrip(client, Read(1, (ReadCommand(Space.X, 0x006C36),)))
    # Responses are padded to the Ethernet minimum (4.1).
    assert len(message) == RESPONSE_MIN_LEN
    assert decode_response(message) == ReadResponse(1, 0x00, (0x474154,))


def test_read_with_64_commands(client):
    connect(client)
    commands = tuple(ReadCommand(Space.X, 0x006C31 + i % 6) for i in range(64))
    message = roundtrip(client, Read(2, commands))
    assert len(message) == 8 + 3 * 64
    assert len(decode_response(message).words) == 64


def test_lost_response(client, modem):
    connect(client)
    modem.faults.drop()
    client.send(Read(1, (ReadCommand(Space.X, 0x006C36),)))
    assert client.receive(timeout=0.2) is None


def test_delayed_response_does_not_block_others(client, modem):
    connect(client)
    modem.faults.delay(0.3, when=reads(0x006C31))
    client.send(Read(1, (ReadCommand(Space.X, 0x006C31),)))
    client.send(Read(2, (ReadCommand(Space.X, 0x006C36),)))
    assert decode_response(client.receive()).seq == 2
    assert decode_response(client.receive()).seq == 1


def test_line_changes_are_visible(client, modem):
    connect(client)
    modem.line.showtime()
    message = roundtrip(client, Read(1, (ReadCommand(Space.X, 0x006C35),)))
    assert decode_response(message).words == (0x000329,)


@pytest.fixture
def foreign_netns(veth):
    """A second network namespace holding the modem side of another veth pair."""
    holder = subprocess.Popen(["unshare", "--net", "sleep", "60"])
    netns = f"/proc/{holder.pid}/ns/net"
    # Wait until the child has entered its namespace.
    deadline = time.monotonic() + 5
    while os.readlink(netns) == os.readlink("/proc/self/ns/net"):
        assert time.monotonic() < deadline, "namespace not created"
        time.sleep(0.01)

    subprocess.run(["ip", "link", "add", "name", "ns-host", "type", "veth",
                    "peer", "name", "ns-modem"], check=True)
    subprocess.run(["ip", "link", "set", "dev", "ns-modem", "netns", str(holder.pid)],
                   check=True)
    subprocess.run(["nsenter", f"--net={netns}", "ip", "link", "set", "dev", "ns-modem", "up"],
                   check=True)
    subprocess.run(["ip", "link", "set", "dev", "ns-host", "up"], check=True)
    yield netns
    holder.kill()
    holder.wait()  # the namespace and its end of the veth pair go away with it


def test_transport_in_another_network_namespace(foreign_netns, modem):
    with Transport(modem, "ns-modem", netns=foreign_netns) as transport:
        client = Client("ns-host", transport.mac)
        try:
            connect(client)
        finally:
            client.close()
