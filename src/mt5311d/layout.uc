// Firmware identification and selection of the address layout
// (MT5311_EBM_Monitoring_Spec.md, section 8.2).

'use strict';

import * as registers from 'mt5311d.registers';

// Identification block, at the same addresses in all layouts.
export const ID_ADDRESSES = [ 0x006c31, 0x006c32, 0x006c33, 0x006c34, 0x006c35, 0x006c36 ];

const SIGNATURE = 0x474154;	// "GAT"

// Build that has been verified to use layout 1.60.
const KNOWN_BUILD = { version: 0x750202, date: 0x090718, time: 0x173044 };

// Constants of the layout check: Xdsl2Band and Xdsl2Unit codes (RFC 5650).
const CHECK = [
	[ 'xdsl2LineBand6', 6 ],
	[ 'xdsl2LineBand7', 8 ],
	[ 'xdsl2LineBand8', 10 ],
	[ 'xdsl2LineBand9', 1 ],
	[ 'xdsl2LineBand10', 2 ],
	[ 'xdsl2ChStatusUnit0', 1 ],
	[ 'xdsl2ChStatusUnit1', 1 ],
];

const LAYOUTS = [ registers.LAYOUT_160, registers.LAYOUT_161 ];

// Splits the words read from ID_ADDRESSES into named raw values.
export function parse_id(words) {
	if (type(words) != 'array' || length(words) != length(ID_ADDRESSES))
		die(`identification block needs ${length(ID_ADDRESSES)} words`);

	return {
		version: words[0],
		date: words[1],
		time: words[2],
		board_type: words[3],
		terminal: words[4],
		signature: words[5],
		valid: words[5] == SIGNATURE,
	};
};

// Addresses to read for the layout check: the check registers of each layout in
// the order of LAYOUTS.
export function check_addresses() {
	const addresses = [];

	for (let layout in LAYOUTS)
		for (let check in CHECK)
			push(addresses, registers.address(layout, check[0]));

	return addresses;
};

function is_known_build(id) {
	return id.version == KNOWN_BUILD.version && id.date == KNOWN_BUILD.date &&
	       id.time == KNOWN_BUILD.time;
}

// Selects the layout from the parsed identification block and the words read
// from check_addresses(). Returns { layout, passed, reason }; layout is null if
// the firmware is not supported.
export function select(id, words) {
	if (type(words) != 'array' || length(words) != length(LAYOUTS) * length(CHECK))
		die(`layout check needs ${length(LAYOUTS) * length(CHECK)} words`);

	if (!id.valid)
		return { layout: null, passed: [], reason: 'invalid signature' };

	const passed = [];

	for (let i = 0; i < length(LAYOUTS); i++) {
		let ok = true;

		for (let j = 0; j < length(CHECK); j++)
			if (words[i * length(CHECK) + j] != CHECK[j][1])
				ok = false;

		if (ok)
			push(passed, LAYOUTS[i]);
	}

	// A known build must also pass the check: if its constants are not where they
	// belong, its addresses cannot be trusted either.
	if (is_known_build(id)) {
		if (registers.LAYOUT_160 in passed)
			return { layout: registers.LAYOUT_160, passed, reason: 'known build' };

		return { layout: null, passed, reason: 'known build fails the layout check' };
	}

	if (length(passed) == 1)
		return { layout: passed[0], passed, reason: 'layout check' };

	return {
		layout: null,
		passed,
		reason: length(passed) ? 'several layouts pass the layout check'
		                       : 'no layout passes the layout check',
	};
};
