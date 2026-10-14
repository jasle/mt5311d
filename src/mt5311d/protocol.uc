// EBM message format (MT5311_EBM_Monitoring_Spec.md, sections 4 to 6.2).
//
// A message is the Ethernet payload after the EtherType. The daemon sends and
// receives through an AF_PACKET datagram socket, so the kernel adds and strips
// the Ethernet header.

'use strict';

import { pack } from 'struct';

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

// Requests are padded to a 64-byte frame without FCS (4.1).
const REQUEST_MIN_LEN = 64 - 14;

const CONNECT1_MARKER = 0xffffffff;
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
