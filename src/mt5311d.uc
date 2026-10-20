#!/usr/bin/ucode
// mt5311d: monitors a Metanoia MT5311 VDSL2 SFP modem and provides its line
// status on ubus as object "dsl", like the Lantiq DSL daemon.
//
//   mt5311d [-c <uci-dir>] [-s <ubus-socket>] [-b <board.json>] [-f]
//   mt5311d -v | -h
//
// -c, -s and -b override the UCI directory, the ubus socket and the path of
// board.json; -f logs to stderr in addition to syslog. -v prints the version,
// -h the usage.

'use strict';

import * as log from 'log';
import * as ubus from 'ubus';
import * as uci from 'uci';
import * as uloop from 'uloop';
import * as board from 'mt5311d.board';
import * as metrics from 'mt5311d.metrics';
import * as poller from 'mt5311d.poller';
import * as session from 'mt5311d.session';

const VERSION = '0.2.0';
const BOARD_ENTRY = { type: 'vdsl' };
const USAGE = 'usage: mt5311d [-c <uci-dir>] [-s <ubus-socket>] [-b <board.json>] [-f]\n' +
              '       mt5311d -v | -h\n';

function parse_args(argv) {
	const args = { confdir: null, socket: null, board: '/etc/board.json', stderr: false };
	const flags = { '-f': 'stderr', '-v': 'version', '-h': 'help' };

	for (let i = 0; i < length(argv); i++) {
		const option = argv[i];

		if (option in flags) {
			args[flags[option]] = true;
			continue;
		}

		const value = argv[++i];

		if (value == null || !(option in [ '-c', '-s', '-b' ]))
			return null;

		args[{ '-c': 'confdir', '-s': 'socket', '-b': 'board' }[option]] = value;
	}

	return args;
}

const args = parse_args(ARGV);

if (args == null) {
	warn(USAGE);
	exit(1);
}

if (args.version) {
	print(`mt5311d ${VERSION}\n`);
	exit(0);
}

if (args.help) {
	print(USAGE);
	exit(0);
}

log.ulog_open(args.stderr ? log.ULOG_SYSLOG | log.ULOG_STDIO : log.ULOG_SYSLOG,
              log.LOG_DAEMON, 'mt5311d');

function info(message) {
	log.ulog(log.LOG_INFO, '%s\n', message);
}

function error(message) {
	log.ulog(log.LOG_ERR, '%s\n', message);
}

function fail(message) {
	error(message);
	exit(1);
}

// Reads /etc/config/mt5311d, section 'main'. Returns null after logging an error.
function load_config() {
	const cursor = args.confdir ? uci.cursor(args.confdir) : uci.cursor();
	const section = cursor.get_all('mt5311d', 'main');

	if (section == null)
		return fail('no configuration: section mt5311d.main is missing');

	const interface = section.interface;
	const macaddr = lc(section.macaddr ?? '');
	const interval = +(section.interval ?? 30);
	const max_age = +(section.max_age ?? 5);

	if (!length(interface))
		return fail('option interface is missing');

	if (!match(macaddr, /^([0-9a-f]{2}:){5}[0-9a-f]{2}$/))
		return fail(`option macaddr is not a MAC address: '${section.macaddr ?? ''}'`);

	if (!(interval > 0) || !(max_age >= 0))
		return fail('options interval and max_age must be numbers of seconds');

	return { interface, macaddr, interval: int(interval * 1000), max_age: int(max_age * 1000) };
}

const config = load_config();

uloop.init();

const conn = ubus.connect(args.socket);

if (conn == null)
	fail(`cannot connect to ubus: ${ubus.error()}`);

const modem = session.create({ interface: config.interface, mac: config.macaddr });
const open_error = modem.open();

if (open_error)
	fail(open_error);

// Logs changes of the poller status and adds the board entry once a supported
// modem has been reached.
let last_report = null;
let board_added = false;

function on_update(state) {
	const report = `${state.status} ${state.reason ?? ''}`;

	if (report != last_report) {
		last_report = report;

		if (state.status == 'ok')
			info(sprintf('modem %s: firmware %06x (%s %s), address layout %s',
			             config.macaddr, state.firmware.version, state.firmware.date,
			             state.firmware.time, state.layout));
		else if (state.status != 'connecting')
			error(`modem ${config.macaddr}: ${state.status}: ${state.reason}`);
	}

	if (state.status == 'ok' && !board_added) {
		board_added = true;

		const result = board.add(args.board, BOARD_ENTRY);

		if (result == 'foreign')
			info(`${args.board} has a DSL modem entry of the board; leaving it`);
		else if (result != 'changed' && result != 'unchanged')
			error(`cannot add the DSL modem entry: ${result}`);
	}
}

const p = poller.create(modem, {
	interval: config.interval,
	max_age: config.max_age,
	on_update,
});

const daemon_info = { version: VERSION };

// ucode rejects every argument that is not listed in args. Calls through
// uhttpd (LuCI) carry the session ID, so it has to be accepted (as a string).
function method(build) {
	return {
		call: function(req) {
			req.defer();
			p.refresh((state) => req.reply(build(state)));
		},
		args: { ubus_rpc_session: '' },
	};
}

const object = conn.publish('dsl', {
	metrics: method((state) => metrics.metrics(state, daemon_info)),
	statistics: method((state) => metrics.statistics(state)),
});

if (object == null)
	fail(`cannot publish ubus object dsl: ${ubus.error()}`);

function shutdown() {
	const result = board.remove(args.board);

	if (result != 'changed' && result != 'unchanged' && result != 'foreign')
		error(`cannot remove the DSL modem entry: ${result}`);

	p.stop();
	modem.close();
	object.remove();
	conn.disconnect();
	uloop.end();
}

uloop.signal('SIGTERM', shutdown);
uloop.signal('SIGINT', shutdown);

info(`mt5311d ${VERSION} started on ${config.interface} for modem ${config.macaddr}`);
p.start();
uloop.run();
info('stopped');
