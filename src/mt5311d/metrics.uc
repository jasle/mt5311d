// Mapping of the poller state to the ubus interface of the Lantiq DSL daemon
// (dsl_cpe_ubus.c in OpenWrt, object "dsl"), which LuCI and the Prometheus and
// collectd exporters read. Fields without a source on the MT5311 are left out,
// as the Lantiq daemon does for values it cannot provide.

'use strict';

// Line states and their numbers in the Lantiq daemon.
const LINE_STATES = {
	idle: [ 'Idle', 2 ],
	handshake: [ 'Handshake', 4 ],
	training: [ 'Full init', 5 ],
	showtime: [ 'Showtime with TC-Layer sync', 7 ],
};
const NOT_INITIALIZED = [ 'Not initialized', 0 ];
const EXCEPTION = [ 'Exception', 1 ];

// G.994.1 provider codes with country code B500 that the Lantiq daemon names.
const VENDORS = {
	ALCB: 'Alcatel',
	ANDV: 'Analog Devices',
	BDCM: 'Broadcom',
	CENT: 'Centillium',
	GSPN: 'Globespan',
	IKNS: 'Ikanos',
	IFTN: 'Infineon',
	TSTC: 'Texas Instruments',
	TMMB: 'Thomson MultiMedia Broadband',
	TCTN: 'Trend Chip Technologies',
	STMI: 'ST Micro',
};

// Standards as the Lantiq daemon names them, and their mode descriptions.
const STANDARDS = {
	'ANSI T1.413': [ 'T1.413', 'T1.413' ],
	'ETSI TS 101 388': [ 'TS 101 388', 'TS 101 388' ],
	'G.992.1': [ 'G.992.1', 'G.992.1 (ADSL)' ],
	'G.992.2': [ 'G.992.2', 'G.992.2 (ADSL lite)' ],
	'G.992.3': [ 'G.992.3', 'G.992.3 (ADSL2)' ],
	'G.992.4': [ 'G.992.4', 'G.992.4 (ADSL2 lite)' ],
	'G.992.5': [ 'G.992.5', 'G.992.5 (ADSL2+)' ],
	'G.993.2': [ 'G.993.2', 'G.993.2 (VDSL2)' ],
};

// Registers per direction: downstream is received by the device (RT), upstream
// by the peer (9.1).
const DIRECTIONS = {
	downstream: {
		data_rate: 'xdsl2ChStatusActDataRate2',
		attndr: 'xdsl2LineStatusAttainableRateDs',
		interleave_delay: 'xdsl2ChStatusActDelay2',
		inp: 'xdsl2ChStatusActInp2',
		snr: 'xdsl2LineBandStatusSnrMargin10',
		latn: 'xdsl2LineBandStatusLnAtten10',
		satn: 'xdsl2LineBandStatusSigAtten10',
		actatp: 'xdsl2LineStatusActAtpDs',
		trellis: 'xdsl2LineStatusTrellisDs',
		virtual_noise: 'xdsl2LineStatusActSnrModeDs',
	},
	upstream: {
		data_rate: 'xdsl2ChStatusActDataRate0',
		attndr: 'xdsl2LineStatusAttainableRateUs',
		interleave_delay: 'xdsl2ChStatusActDelay0',
		inp: 'xdsl2ChStatusActInp0',
		snr: 'xdsl2LineBandStatusSnrMargin9',
		// No latn/satn: on an RT device the upstream totals are not available (9.1).
		actatp: 'xdsl2LineStatusActAtpUs',
		trellis: 'xdsl2LineStatusTrellisUs',
		virtual_noise: 'xdsl2LineStatusActSnrModeUs',
	},
};

// Error counters since start-up: near end (downstream, measured by the device)
// and far end (upstream, reported by the peer) (9.1).
const ERRORS = {
	near: {
		cv_c: 'xdslMetanoiaRtCodingViolations0',
		fec_c: 'xdslMetanoiaRtCorrectedBlocks0',
		fecs: 'xdslMetanoiaRtFecs0',
		es: 'xdslMetanoiaRtEs0',
		ses: 'xdslMetanoiaRtSes0',
		loss: 'xdslMetanoiaRtLoss0',
		uas: 'xdslMetanoiaRtUas0',
	},
	far: {
		cv_c: 'xdslMetanoiaRtCodingViolations1',
		fec_c: 'xdslMetanoiaRtCorrectedBlocks1',
	},
};

function bytes(text) {
	const result = [];

	for (let i = 0; i < length(text); i++)
		push(result, ord(text, i));

	return result;
}

// Fields for the transceiver at the network side (atu_c).
function atu_c(values) {
	const result = {};
	const vendor = values.xdsl2LInvG994VendorId0;

	if (vendor != null) {
		const id = bytes(hexdec(vendor.raw));
		const name = (vendor.country == 'b500') ? VENDORS[vendor.provider] : null;

		result.vendor_id = id;

		if (name != null)
			result.vendor = (id[6] || id[7]) ? `${name} ${id[6]}.${id[7]}` : name;
	}

	if (values.xdsl2LInvVersionNumber0 != null)
		result.version = bytes(values.xdsl2LInvVersionNumber0);

	return result;
}

function direction(values, registers) {
	const result = {};
	const v = (name) => values[registers[name]];

	if (v('trellis') != null)
		result.trellis = v('trellis');

	if (v('virtual_noise')?.name != null)
		result.virtual_noise = v('virtual_noise').name == 'enabled';

	if (v('interleave_delay') != null)
		result.interleave_delay = v('interleave_delay') * 1000;	// ms -> µs

	if (v('inp') != null)
		result.inp = v('inp');

	if (v('data_rate') != null)
		result.data_rate = v('data_rate') * 1000;		// kbit/s -> bit/s

	for (let name in [ 'latn', 'satn', 'snr', 'actatp' ])
		if (registers[name] != null && v(name) != null)
			result[name] = v(name);

	if (v('attndr') != null)
		result.attndr = v('attndr') * 1000;

	return result;
}

function errors(counters) {
	const result = {};

	for (let side, fields in ERRORS) {
		result[side] = {};

		for (let field, name in fields)
			if (counters[name] != null)
				result[side][field] = counters[name];
	}

	return result;
}

// Fields of the line mode (standard, annex, profile, mode), only in showtime:
// outside showtime the transmission mode register holds 0, which is not T1.413.
function line_mode(values) {
	const result = {};
	const trans_sys = values.xdsl2LineStatusXtuTransSys;
	const standard = STANDARDS[trans_sys?.standard];

	if (standard == null)
		return result;

	result.standard = standard[0];

	if (trans_sys.annex != null)
		result.annex = trans_sys.annex;

	const profile = values.xdsl2LineStatusActProfile?.name;

	if (standard[0] == 'G.993.2' && profile != null) {
		result.profile = profile;
		result.mode = `G.993.2 (VDSL2, Profile ${profile})`;
	}
	else {
		result.mode = standard[1];
	}

	return result;
}

// The reply of `ubus call dsl metrics` for a poller state. info: { version }
export function metrics(state, info) {
	const result = {
		chipset: 'Metanoia MT5311',
		driver_version: `mt5311d ${info?.version ?? 'unknown'}`,
	};

	if (state.firmware != null)
		result.firmware_version = sprintf('%06x (%s %s)', state.firmware.version,
		                                  state.firmware.date ?? '?', state.firmware.time ?? '?');

	let line_state;

	if (state.status == 'ok')
		line_state = LINE_STATES[state.terminal.line_state];
	else if (state.status == 'unsupported')
		line_state = EXCEPTION;
	else
		line_state = NOT_INITIALIZED;

	result.state = line_state[0];
	result.state_num = line_state[1];
	result.up = state.status == 'ok' && state.showtime;
	result.uptime = result.up ? (state.counters.xdslMetanoiaShowtimeSeconds ?? 0) : 0;

	// LuCI reads these objects whenever `state` is present, so they always exist.
	result.atu_c = {};
	result.downstream = {};
	result.upstream = {};
	result.errors = { near: {}, far: {} };

	if (state.status != 'ok')
		return result;

	result.atu_c = atu_c(state.values);
	result.errors = errors(state.counters);

	if (state.showtime) {
		for (let name, value in line_mode(state.values))
			result[name] = value;

		for (let name, registers in DIRECTIONS)
			result[name] = direction(state.values, registers);
	}

	return result;
};
