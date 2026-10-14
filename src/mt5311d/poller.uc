// Poller: keeps the state of the modem up to date over a session
// (MT5311_EBM_Monitoring_Spec.md, sections 6.4, 7.2, 8.2, 9 and 11).
//
// A poll cycle connects if needed, identifies the firmware and selects the
// address layout, then reads the identification block followed by all registers
// of the register table. A register that cannot be read is skipped instead of
// ending the session (6.4). Cycles run on demand (refresh) and, once started, in
// the background at a fixed interval, so that counter overflows and retrains are
// seen even when nobody asks. Measurement values are only reported in showtime; the
// 24-bit counters are extended to counters without overflow since the start of
// the showtime.

'use strict';

import * as uloop from 'uloop';
import * as layout from 'mt5311d.layout';
import * as registers from 'mt5311d.registers';
import * as protocol from 'mt5311d.protocol';
import * as values from 'mt5311d.values';

const DEFAULTS = {
	interval: 30000,	// ms between background cycles
	max_age: 1000,		// ms during which refresh() returns the last state
	reconnect_delay: 1000,	// ms after a failed connection attempt (6.4)
	holdoff: 300000,	// ms before a register without response is read again
	holdoff_max: 3600000,	// limit when the hold-off doubles after each failure
};

// Registers that need more than their own words to be decoded (9.2.4).
const VERSION_NUMBERS = [ 'xdsl2LInvVersionNumber0', 'xdsl2LInvVersionNumber1' ];

const SHOWTIME_SECONDS = 'xdslMetanoiaShowtimeSeconds';
const FAILURE_REASON = 'xdsl2MetanoiaRtFailureReasons';

function now_ms() {
	const t = clock(true);

	return t[0] * 1000 + t[1] / 1000000;
}

function same_identity(a, b) {
	return a.version == b.version && a.date == b.date && a.time == b.time &&
	       a.signature == b.signature;
}

// Creates a poller for an open session.
// options: { interval?, max_age?, reconnect_delay?, holdoff?, holdoff_max? }
export function create(session, options) {
	const config = { ...DEFAULTS, ...options };

	let connected = false;
	let last_attempt = null;	// end of the last failed connection attempt, ms
	let id = null;			// identification block at layout selection
	let terminal = null;		// xdslTerminal decoded at layout selection
	let selected = null;		// result of layout.select()
	let plan = null;		// [ { name, addresses } ] for the selected layout
	let previous = null;		// { showtime, raw } of the previous cycle
	let counters = {};
	let unreadable = {};		// name -> true: error response, until the next layout selection
	let suspended = {};		// name -> { until, holdoff }: no response (6.4)
	let busy = false;
	let waiting = [];		// callbacks of refresh() for the running cycle
	let timer = null;		// background cycles, after start()
	let state = { status: 'connecting', reason: null, updated: null };

	function update(fields) {
		state = { ...fields, updated: now_ms() };
	}

	// Forgets everything that belongs to the session (6.4).
	function lose_session(reason) {
		connected = false;
		id = terminal = selected = plan = previous = null;
		counters = {};
		unreadable = {};
		suspended = {};
		update({ status: 'error', reason });
	}

	// Reads any number of addresses in requests of up to MAX_COMMANDS.
	// done({ status: 'ok', words }) or done(failure of the first failing request).
	function read_all(addresses, done, words) {
		words ??= [];

		if (length(words) == length(addresses))
			return done({ status: 'ok', words });

		const chunk = slice(addresses, length(words), length(words) + protocol.MAX_COMMANDS);

		session.read(chunk, (result) => {
			if (result.status != 'ok')
				return done(result);

			read_all(addresses, done, [ ...words, ...result.words ]);
		});
	}

	function connect(done) {
		if (connected)
			return done(true);

		if (last_attempt != null && now_ms() - last_attempt < config.reconnect_delay) {
			update({ status: 'error', reason: 'waiting to reconnect' });
			return done(false);
		}

		session.connect((ok, reason) => {
			connected = ok;
			last_attempt = ok ? null : now_ms();

			if (!ok)
				update({ status: 'error', reason });

			done(ok);
		});
	}

	function make_plan(layout_name) {
		const entries = [];

		for (let name in registers.names()) {
			const base = registers.address(layout_name, name);
			const addresses = [];

			for (let i = 0; i < registers.words(name); i++)
				push(addresses, base + i);

			push(entries, { name, addresses });
		}

		return entries;
	}

	function identification() {
		return {
			firmware: values.firmware(id),
			board_type: id.board_type,
			terminal,
			layout: selected.layout,
		};
	}

	function report_unsupported() {
		const reason = (terminal.role != 'RT')
			? 'device runs as OT (network side); only RT is supported'
			: `firmware not supported: ${selected.reason}`;

		update({ status: 'unsupported', reason, ...identification() });
	}

	// Reads the identification block and the layout check (8.2). done(supported).
	function identify(done) {
		if (selected != null)
			return done(true);

		const check = layout.check_addresses();

		read_all([ ...layout.ID_ADDRESSES, ...check ], (result) => {
			if (result.status != 'ok') {
				lose_session(`identification failed: ${result.status}`);
				return done(false);
			}

			id = layout.parse_id(slice(result.words, 0, length(layout.ID_ADDRESSES)));
			terminal = values.terminal(id.terminal);
			selected = layout.select(id, slice(result.words, length(layout.ID_ADDRESSES)));

			if (selected.layout == null || terminal.role != 'RT') {
				report_unsupported();
				selected = null;	// check again in the next cycle
				return done(false);
			}

			plan = make_plan(selected.layout);
			unreadable = {};
			suspended = {};
			done(true);
		});
	}

	// Extends the 24-bit counters (7.2). A counter starts again from its raw value
	// at a new showtime: when the line was not in showtime in the previous cycle,
	// or when the showtime duration decreased because a whole retrain fell
	// between two cycles.
	function extend_counters(raw, showtime) {
		const seconds = raw[SHOWTIME_SECONDS]?.[0];
		const previous_seconds = previous?.raw[SHOWTIME_SECONDS]?.[0];
		const reset = previous == null || !previous.showtime || !showtime ||
			(seconds != null && previous_seconds != null && seconds < previous_seconds);

		const extended = {};

		for (let entry in plan) {
			const name = entry.name;

			if (values.format(name).class != 'C' || raw[name] == null)
				continue;

			extended[name] = (reset || counters[name] == null || previous.raw[name] == null)
				? raw[name][0]
				: counters[name] + values.counter_delta(previous.raw[name][0], raw[name][0]);
		}

		counters = extended;
	}

	function evaluate(raw) {
		const line = values.terminal(raw.xdslTerminal[0]);
		const showtime = line.showtime;
		const decoded = {};

		for (let entry in plan) {
			const name = entry.name;
			const fmt = values.format(name);

			if (raw[name] == null)
				decoded[name] = null;	// not readable in this cycle
			else if (name in VERSION_NUMBERS)
				decoded[name] = (raw.xdslTwConfig3 != null)
					? values.version_number(raw[name], raw.xdslTwConfig3[0]) : null;
			else if (fmt.class == 'M' && !showtime)
				decoded[name] = null;	// only meaningful in showtime (7.3)
			else
				decoded[name] = values.decode(name, raw[name]);
		}

		extend_counters(raw, showtime);
		previous = { showtime, raw };

		update({
			status: 'ok',
			reason: null,
			...identification(),
			terminal: line,
			showtime,
			values: decoded,
			counters: showtime ? counters : {},	// counters of the current showtime
			failure_reason: decoded[FAILURE_REASON],
			unreadable: sort(keys(unreadable)),
			suspended: sort(keys(suspended)),
		});
	}

	// Reads addresses one per request. done(words, failures): words has null for
	// failed addresses, failures maps an address to 'error' or 'timeout'. With
	// stop_on_failure, reading ends at the first failure.
	function read_singly(addresses, done, stop_on_failure, words, failures) {
		words ??= [];
		failures ??= {};

		if (length(words) == length(addresses) || (stop_on_failure && length(failures)))
			return done(words, failures);

		const address = addresses[length(words)];

		session.read([ address ], (result) => {
			if (result.status == 'ok') {
				push(words, result.words[0]);
			}
			else {
				push(words, null);
				failures[address] = result.status;
			}

			read_singly(addresses, done, stop_on_failure, words, failures);
		});
	}

	// Handles a failed request (6.4): the identification block is read with
	// single requests; if that fails too, the session has failed (done(null)).
	// Otherwise the addresses of the request are read one by one.
	function recover(chunk, failure, done) {
		read_singly(layout.ID_ADDRESSES, (words, failures) => {
			if (length(failures)) {
				lose_session(`read failed: ${failure.status}`);
				return done(null);
			}

			if (length(chunk) == 1)
				return done([ null ], { [chunk[0]]: failure.status });

			read_singly(chunk, done, false);
		}, true);
	}

	// Reads addresses in requests of up to MAX_COMMANDS, recovering from failed
	// requests. done(words, failures), or done(null) after a session error.
	function read_robust(addresses, done, words, failures) {
		words ??= [];
		failures ??= {};

		if (length(words) == length(addresses))
			return done(words, failures);

		const chunk = slice(addresses, length(words), length(words) + protocol.MAX_COMMANDS);

		session.read(chunk, (result) => {
			if (result.status == 'ok')
				return read_robust(addresses, done, [ ...words, ...result.words ], failures);

			recover(chunk, result, (chunk_words, chunk_failures) => {
				if (chunk_words == null)
					return done(null);

				read_robust(addresses, done, [ ...words, ...chunk_words ],
				            { ...failures, ...chunk_failures });
			});
		});
	}

	// Marks registers with failed addresses: unreadable after an error response,
	// suspended with a growing hold-off after a missing response (6.4).
	function mark(entries, failures) {
		const now = now_ms();

		for (let entry in entries) {
			let error = false, timeout = false;

			for (let address in entry.addresses) {
				error ||= failures[address] == 'error';
				timeout ||= failures[address] == 'timeout';
			}

			if (error) {
				unreadable[entry.name] = true;
				delete suspended[entry.name];
				warn(`mt5311d: register ${entry.name} is not readable; skipping it\n`);
			}
			else if (timeout) {
				const holdoff = suspended[entry.name]
					? min(suspended[entry.name].holdoff * 2, config.holdoff_max)
					: config.holdoff;

				suspended[entry.name] = { until: now + holdoff, holdoff };
				warn(`mt5311d: no response for register ${entry.name}; ` +
				     `retrying in ${int(holdoff / 1000)} s\n`);
			}
			else {
				delete suspended[entry.name];
			}
		}
	}

	// Registers to read in this cycle: neither unreadable nor in their hold-off.
	function active_entries() {
		const now = now_ms();

		return filter(plan, (entry) => !unreadable[entry.name] &&
			!(suspended[entry.name]?.until > now));
	}

	// Reads the identification block and the registers of the plan (11).
	function poll(done) {
		const entries = active_entries();
		const addresses = [ ...layout.ID_ADDRESSES ];

		for (let entry in entries)
			push(addresses, ...entry.addresses);

		read_robust(addresses, (words, failures) => {
			if (words == null)
				return done(false);

			const current = layout.parse_id(slice(words, 0, length(layout.ID_ADDRESSES)));

			// A changed identification means another firmware or a reset device;
			// it needs a new session and a new layout selection (6.4).
			if (!current.valid || !same_identity(current, id)) {
				lose_session('identification changed');
				return done(false);
			}

			mark(entries, failures);

			const raw = {};
			let offset = length(layout.ID_ADDRESSES);

			for (let entry in entries) {
				const entry_words = slice(words, offset, offset + length(entry.addresses));

				if (!(null in entry_words))
					raw[entry.name] = entry_words;

				offset += length(entry.addresses);
			}

			// xdslTerminal is part of the identification block.
			raw.xdslTerminal ??= [ current.terminal ];

			evaluate(raw);
			done(true);
		});
	}

	// One poll cycle. A session error in the middle of a cycle is followed by
	// one new attempt within the same cycle (6.4).
	function cycle(done, retry) {
		connect((ok) => {
			if (!ok)
				return done();

			identify((supported) => {
				if (!connected)
					return retry ? cycle(done, false) : done();

				if (!supported)
					return done();

				poll((ok) => (!ok && retry) ? cycle(done, false) : done());
			});
		});
	}

	// Runs a cycle and then passes the state to all waiting callbacks. The next
	// background cycle follows one interval after the end of any cycle.
	function run_cycle() {
		busy = true;

		cycle(() => {
			const callbacks = waiting;

			busy = false;
			waiting = [];

			if (timer)
				timer.set(config.interval);

			for (let callback in callbacks)
				callback(state);
		}, true);
	}

	function on_timer() {
		if (!busy)
			run_cycle();
	}

	return {
		// Starts the background cycles, beginning with one cycle now.
		start: function() {
			if (timer)
				return;

			timer = uloop.timer(null, on_timer);

			if (!busy)
				run_cycle();
		},

		// Stops the background cycles; a running cycle still completes.
		stop: function() {
			if (timer)
				timer.cancel();

			timer = null;
		},

		// Passes the current state to callback: at once if it is younger than
		// max_age, otherwise after a new cycle. Calls during a running cycle wait
		// for its result.
		refresh: function(callback) {
			if (busy)
				return push(waiting, callback);

			if (state.updated != null && now_ms() - state.updated < config.max_age)
				return callback(state);

			push(waiting, callback);
			run_cycle();
		},

		// The state of the last cycle.
		state: function() {
			return state;
		},
	};
};
