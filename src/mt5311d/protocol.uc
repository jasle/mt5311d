// EBM message format (MT5311_EBM_Monitoring_Spec.md, sections 4 to 6.2).
//
// A message is the Ethernet payload after the EtherType. The daemon sends and
// receives through an AF_PACKET datagram socket, so the kernel adds and strips
// the Ethernet header.

'use strict';

import { pack, unpack } from 'struct';

export const ETHERTYPE = 0x6120;

export const TYPE_READ = 0x01;
export const TYPE_CONNECT = 0x31;
export const TYPE_DISCONNECT = 0x50;
export const RESPONSE_BIT = 0x80;

export const STATUS_REQUEST = 0xff;
export const STATUS_OK = 0x00;
export const STATUS_CONNECT1 = 0xe0;
export const STATUS_CONNECT2 = 0xe1;

export const SPACE_X = 1;
export const WORD_BYTES = 3;
export const MAX_COMMANDS = 64;

const HEADER_LEN = 8;

// Requests are padded to a 64-byte frame without FCS (4.1).
const REQUEST_MIN_LEN = 64 - 14;

const CONNECT1_MARKER = 0xffffffff;
const CONNECT1_MAGIC = 0x95743926;
const CONNECT2_KEY = 'noia';

function check_uint(name, value, max) {
	if (type(value) != 'int' || value < 0 || value > max)
		die(`invalid ${name}: ${value}`);
}

// Header (4.2) with Length = payload length (4.3), padded to the minimum size.
function request(msg_type, seq, payload) {
	check_uint('sequence', seq, 0xffffffff);

	const msg = pack('>HBIB', length(payload), msg_type, seq, STATUS_REQUEST) + payload;
	const pad = REQUEST_MIN_LEN - length(msg);

	return pad > 0 ? msg + pack(`${pad}x`) : msg;
}

// CONNECT stage 1 (5.1).
export function connect1(seq) {
	return request(TYPE_CONNECT, seq, pack('>II', CONNECT1_MARKER, 0));
};

// CONNECT stage 2 (5.1): Length covers only the key.
export function connect2(seq) {
	return request(TYPE_CONNECT, seq, CONNECT2_KEY);
};

// READ of one word per address in space X (5.2), up to MAX_COMMANDS commands (5.5).
export function read(seq, addresses) {
	if (type(addresses) != 'array' || length(addresses) < 1 ||
	    length(addresses) > MAX_COMMANDS)
		die(`READ needs 1 to ${MAX_COMMANDS} addresses`);

	let payload = '';

	for (let address in addresses) {
		check_uint('address', address, 0xffffff);
		payload += pack('>BBHH', SPACE_X, address >> 16, address & 0xffff, WORD_BYTES);
	}

	return request(TYPE_READ, seq, payload);
};

// DISCONNECT (5.4).
export function disconnect(seq) {
	return request(TYPE_DISCONNECT, seq, '');
};

// Parses a received response (4.2 to 5.5). Bytes after the Length field are
// padding. Returns null for anything that is not a valid response, e.g. a
// truncated frame or the legacy short format (5.6).
//
// CONNECT: { type, seq, status, stage }
// READ:    { type, seq, status, words } (words is empty for an error response)
export function decode(message) {
	if (type(message) != 'string' || length(message) < HEADER_LEN)
		return null;

	const header = unpack('>HBIB', message);
	const len = header[0], msg_type = header[1], seq = header[2], status = header[3];

	// In a response, Length covers Type, Sequence, Status and the payload (4.3).
	if (len < HEADER_LEN - 2 || length(message) < 2 + len)
		return null;

	const payload = substr(message, HEADER_LEN, len - (HEADER_LEN - 2));

	if (msg_type == (TYPE_CONNECT | RESPONSE_BIT)) {
		if (status == STATUS_CONNECT1 && length(payload) >= 8 &&
		    unpack('>I', payload, 4)[0] == CONNECT1_MAGIC)
			return { type: msg_type, seq, status, stage: 1 };

		if (status == STATUS_CONNECT2)
			return { type: msg_type, seq, status, stage: 2 };

		return null;
	}

	if (msg_type == (TYPE_READ | RESPONSE_BIT)) {
		if (length(payload) % WORD_BYTES)
			return null;

		const words = [];

		if (status == STATUS_OK)
			for (let i = 0; i < length(payload); i += WORD_BYTES)
				push(words, (ord(payload, i) << 16) | (ord(payload, i + 1) << 8) |
				            ord(payload, i + 2));

		return { type: msg_type, seq, status, words };
	}

	return null;
};

// Tells whether a decoded response answers the outstanding request (6.2).
//
// expected describes the request: { mac, type, seq } plus stage for CONNECT and
// count (number of commands) for READ. source is the sender's MAC address. A
// READ response with an error status matches; the caller handles it (6.4).
export function matches(expected, source, response) {
	if (response == null || type(source) != 'string' || lc(source) != lc(expected.mac))
		return false;

	if (response.type != (expected.type | RESPONSE_BIT) || response.seq != expected.seq)
		return false;

	if (expected.type == TYPE_CONNECT)
		return response.stage == expected.stage;

	if (expected.type == TYPE_READ)
		return response.status != STATUS_OK || length(response.words) == expected.count;

	return false;
};
