// Session with the modem over an AF_PACKET socket, driven by uloop
// (MT5311_EBM_Monitoring_Spec.md, sections 6.1 to 6.3).
//
// A session runs one transaction at a time: it sends a request, retransmits it
// with the same sequence number until a matching response arrives or the attempts
// are used up, and reports the outcome to a callback. What to do after a failure
// (6.4) is up to the caller.

'use strict';

import * as socket from 'socket';
import * as uloop from 'uloop';
import * as protocol from 'mt5311d.protocol';

const DEFAULTS = {
	timeout: 200,	// ms per attempt (6.3)
	attempts: 3,
	interval: 5,	// ms between a response and the next request (6.3)
};

const MAX_FRAME = 1514;

function now_ms() {
	const t = clock(true);

	return t[0] * 1000 + t[1] / 1000000;
}

// Creates a session. options: { interface, mac, timeout?, attempts?, interval? }
export function create(options) {
	const config = { ...DEFAULTS, ...options };

	if (type(config.interface) != 'string' || type(config.mac) != 'string')
		die('session needs an interface and the modem MAC address');

	const peer = {
		family: socket.AF_PACKET,
		interface: config.interface,
		protocol: protocol.ETHERTYPE,
		address: lc(config.mac),
	};

	let sock = null;
	let handle = null;
	let timer = null;
	let seq = 1;
	let pending = null;	// { message, expected, attempts, callback }
	let last_done = 0;	// end of the previous transaction, ms

	function transmit() {
		pending.attempts++;

		if (sock.send(pending.message, 0, peer) == null)
			warn(`mt5311d: send on ${config.interface} failed: ${sock.error()}\n`);

		timer.set(config.timeout);
	}

	// The timer is not cancelled here: cancel() releases a uloop timer for good,
	// and set() on it afterwards never fires. The next transaction re-arms it with
	// set(); a firing without a transaction is ignored by on_timer().
	function finish(result) {
		const transaction = pending;

		pending = null;
		last_done = now_ms();
		transaction.callback(result);
	}

	function on_timer() {
		if (pending == null)
			return;

		if (pending.attempts < config.attempts)
			transmit();
		else
			finish(null);
	}

	function on_readable() {
		// A callback may close the session while frames are still queued.
		while (sock != null) {
			const source = {};
			const message = sock.recv(MAX_FRAME, socket.MSG_DONTWAIT, source);

			if (message == null)
				break;

			if (pending == null || source.packet_type == socket.PACKET_OUTGOING)
				continue;

			const response = protocol.decode(message);

			if (protocol.matches(pending.expected, source.address, response))
				finish(response);
		}
	}

	// Starts a transaction; on_response gets the matching response or null.
	function start(message, expected, on_response) {
		if (sock == null)
			die('session is not open');

		if (pending)
			die('a request is already outstanding');

		pending = { message, expected, attempts: 0, callback: on_response };

		const wait = last_done + config.interval - now_ms();

		if (wait > 0)
			timer.set(int(wait) + 1);	// on_timer sends the first attempt
		else
			transmit();
	}

	return {
		// Opens the socket on the interface. Returns null or an error message.
		open: function() {
			if (sock)
				return null;

			sock = socket.create(socket.AF_PACKET, socket.SOCK_DGRAM, 0);

			if (sock == null)
				return `socket: ${socket.error()}`;

			// The socket module needs an address also for bind(), which ignores it.
			if (!sock.bind({ ...peer, address: '00:00:00:00:00:00' })) {
				const error = `bind to ${config.interface}: ${sock.error()}`;

				sock.close();
				sock = null;

				return error;
			}

			handle = uloop.handle(sock, on_readable, uloop.ULOOP_READ);
			timer = uloop.timer(null, on_timer);	// armed per transaction

			return null;
		},

		// CONNECT in two stages (5.1). callback(ok, reason). CONNECT does not
		// advance the sequence number (6.2).
		connect: function(callback) {
			const expected = { mac: peer.address, type: protocol.TYPE_CONNECT, seq, stage: 1 };

			start(protocol.connect1(seq), expected, (response) => {
				if (response == null)
					return callback(false, 'no response to CONNECT stage 1');

				start(protocol.connect2(seq), { ...expected, stage: 2 }, (response) => {
					if (response == null)
						return callback(false, 'no response to CONNECT stage 2');

					callback(true, null);
				});
			});
		},

		// READ of 1 to 64 addresses. callback receives
		//   { status: 'ok', words }    words in the order of the addresses
		//   { status: 'error', code }  error response (6.2)
		//   { status: 'timeout' }      no matching response after all attempts
		// The sequence number advances in every case (6.2).
		read: function(addresses, callback) {
			const expected = {
				mac: peer.address, type: protocol.TYPE_READ, seq, count: length(addresses),
			};

			start(protocol.read(seq, addresses), expected, (response) => {
				seq = (seq + 1) & 0xffffffff;

				if (response == null)
					callback({ status: 'timeout' });
				else if (response.status != protocol.STATUS_OK)
					callback({ status: 'error', code: response.status });
				else
					callback({ status: 'ok', words: response.words });
			});
		},

		// Closes the socket. An outstanding transaction is dropped without callback.
		close: function() {
			pending = null;

			if (timer)
				timer.cancel();

			if (handle)
				handle.delete();

			if (sock)
				sock.close();

			sock = handle = timer = null;
		},
	};
};
