// The DSL modem entry in /etc/board.json, by which LuCI shows the DSL status.
//
// LuCI shows the DSL status box only if board.json has an object dsl.modem;
// boards with a built-in modem get it when board.json is generated. The daemon
// adds its own entry while it reaches a supported modem and removes it when it
// stops. Entries are marked with managed_by, so that an entry of the board is
// never changed. The file is only written when its content changes, and atomically.

'use strict';

import * as fs from 'fs';

export const MANAGED_BY = 'mt5311d';

function load(path) {
	const text = fs.readfile(path);

	if (text == null)
		return [ null, `${path}: ${fs.error()}` ];

	let board;

	try {
		board = json(text);
	}
	catch (e) {
		return [ null, `${path}: ${e.message}` ];
	}

	return (type(board) == 'object') ? [ board, null ] : [ null, `${path}: not an object` ];
}

function save(path, board) {
	const temporary = `${path}.${MANAGED_BY}`;

	if (fs.writefile(temporary, sprintf('%.J\n', board)) == null)
		return `${temporary}: ${fs.error()}`;

	if (!fs.rename(temporary, path)) {
		const error = `${path}: ${fs.error()}`;

		fs.unlink(temporary);

		return error;
	}

	return 'changed';
}

function is_ours(modem) {
	return type(modem) == 'object' && modem.managed_by == MANAGED_BY;
}

// Adds or updates dsl.modem with the fields of modem. Returns 'changed',
// 'unchanged', 'foreign' (the board has its own entry) or an error message.
export function add(path, modem) {
	const loaded = load(path);
	const board = loaded[0];

	if (board == null)
		return loaded[1];

	const entry = { ...modem, managed_by: MANAGED_BY };
	const current = board.dsl?.modem;

	if (current != null && !is_ours(current))
		return 'foreign';

	if (sprintf('%J', current) == sprintf('%J', entry))
		return 'unchanged';

	if (type(board.dsl) != 'object')
		board.dsl = {};

	board.dsl.modem = entry;

	return save(path, board);
};

// Removes our dsl.modem entry. Returns 'changed', 'unchanged', 'foreign' or an
// error message.
export function remove(path) {
	const loaded = load(path);
	const board = loaded[0];

	if (board == null)
		return loaded[1];

	const current = board.dsl?.modem;

	if (current == null)
		return 'unchanged';

	if (!is_ours(current))
		return 'foreign';

	delete board.dsl.modem;

	if (length(board.dsl) == 0)
		delete board.dsl;

	return save(path, board);
};
