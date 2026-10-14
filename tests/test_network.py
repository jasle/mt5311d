"""The test network: ucode in the container talks to the simulator in pytest."""

from conftest import DAEMON_INTERFACE


def test_connect_with_the_simulator(ucode, simulator):
    source = """
        import * as socket from 'socket';
        import * as p from 'mt5311d.protocol';

        const peer = { family: socket.AF_PACKET, interface: IFACE, protocol: p.ETHERTYPE,
                       address: MAC };
        const sock = socket.create(socket.AF_PACKET, socket.SOCK_DGRAM, 0);
        sock.bind({ ...peer, address: '00:00:00:00:00:00' });
        sock.send(p.connect1(1), 0, peer);

        let response = null;
        while (response == null && socket.poll(1000, sock)[0][1] & socket.POLLIN) {
            const from = {};
            const message = sock.recv(1514, 0, from);
            if (from.packet_type != socket.PACKET_OUTGOING)
                response = { source: from.address, message: p.decode(message) };
        }
        printf('%J', response);
    """
    response = ucode.run(source, IFACE=DAEMON_INTERFACE, MAC=simulator.mac)
    # The socket module reports MAC addresses in upper case.
    assert response == {
        "source": simulator.mac.upper(),
        "message": {"type": 0xB1, "seq": 1, "status": 0xE0, "stage": 1},
    }
