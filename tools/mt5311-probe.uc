// Diagnostic tool: reads an MT5311 modem once and prints what it finds as JSON.
//
//   ucode -L '<repository>/src/*.uc' mt5311-probe.uc <interface> <modem-mac>
//
// It connects, reads the identification block, selects the address layout and,
// for a supported firmware, reads and decodes all registers mt5311d knows. It only
// sends CONNECT and READ requests.

'use strict';

import * as uloop from 'uloop';
import * as session from 'mt5311d.session';
import * as layout from 'mt5311d.layout';
import * as registers from 'mt5311d.registers';
import * as protocol from 'mt5311d.protocol';
import * as values from 'mt5311d.values';

const VERSION_NUMBERS = [ 'xdsl2LInvVersionNumber0', 'xdsl2LInvVersionNumber1' ];

function fail(message) {
	warn(`mt5311-probe: ${message}\n`);
	exit(1);
}

if (length(ARGV) != 2)
	fail('usage: ucode -L \'<repository>/src/*.uc\' mt5311-probe.uc <interface> <modem-mac>');

uloop.init();

const s = session.create({ interface: ARGV[0], mac: ARGV[1] });
const error = s.open();

if (error)
	fail(error);

// Reads addresses in requests of up to MAX_COMMANDS; done(words) or fail().
function read_all(addresses, done, words) {
	words ??= [];

	if (length(words) == length(addresses))
		return done(words);

	const chunk = slice(addresses, length(words), length(words) + protocol.MAX_COMMANDS);

	s.read(chunk, (result) => {
		if (result.status != 'ok')
			fail(`READ failed: ${result.status}${result.code != null ? ' ' + result.code : ''}`);

		read_all(addresses, done, [ ...words, ...result.words ]);
	});
}

function report(result) {
	printf('%.J\n', result);
	s.close();
	uloop.end();
}

function read_registers(result) {
	const names = registers.names();
	const addresses = [];

	for (let name in names)
		for (let i = 0; i < registers.words(name); i++)
			push(addresses, registers.address(result.layout.layout, name) + i);

	read_all(addresses, (words) => {
		const raw = {};
		let offset = 0;

		for (let name in names) {
			raw[name] = slice(words, offset, offset + registers.words(name));
			offset += registers.words(name);
		}

		result.values = {};

		for (let name in names)
			result.values[name] = (name in VERSION_NUMBERS)
				? values.version_number(raw[name], raw.xdslTwConfig3[0])
				: values.decode(name, raw[name]);

		report(result);
	});
}

s.connect((ok, reason) => {
	if (!ok)
		fail(reason);

	const check = layout.check_addresses();

	read_all([ ...layout.ID_ADDRESSES, ...check ], (words) => {
		const id = layout.parse_id(slice(words, 0, length(layout.ID_ADDRESSES)));
		const result = {
			firmware: values.firmware(id),
			board_type: sprintf('%06x', id.board_type),
			signature_valid: id.valid,
			terminal: values.terminal(id.terminal),
			layout: layout.select(id, slice(words, length(layout.ID_ADDRESSES))),
		};

		if (result.layout.layout == null)
			report(result);
		else
			read_registers(result);
	});
});

uloop.run();
