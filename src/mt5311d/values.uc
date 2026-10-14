// Decoding of register values (MT5311_EBM_Monitoring_Spec.md, sections 7 and 9).
//
// Measurement values are returned in the unit of the specification (e.g. dB,
// kbit/s); special values become null. The functions are stateless: whether a
// decreasing counter was reset or wrapped depends on the line history and is
// decided by the caller.

'use strict';

const WORD_BITS = 24;
const WORD_MASK = (1 << WORD_BITS) - 1;
const SIGN_BIT = 1 << (WORD_BITS - 1);

// Special values (7.3). INVALID is only special for unsigned registers: as a
// signed value it is -52, a valid SNR margin of -5.2 dB.
const SPECIAL = [ 0x7fffff, 0x7ffffe, 0xc69a53, 0x19979f ];
const INVALID = 0xffffcc;

// Value class (7.3) and, for measurement values (class M), sign, divisor and unit
// of every register in registers.uc.
const FORMATS = {
	ModemStatus:                         { class: 'E' },
	xdslFirmwareVer:                     { class: 'I' },
	xdslFirmwareDate:                    { class: 'I' },
	xdslFirmwareTime:                    { class: 'I' },
	xdslBoardType:                       { class: 'I' },
	xdslTerminal:                        { class: 'E' },
	xdslMetanoiaSignature:               { class: 'I' },

	xdsl2LineBand6:                      { class: 'E' },
	xdsl2LineBand7:                      { class: 'E' },
	xdsl2LineBand8:                      { class: 'E' },
	xdsl2LineBand9:                      { class: 'E' },
	xdsl2LineBand10:                     { class: 'E' },
	xdsl2ChStatusUnit0:                  { class: 'E' },
	xdsl2ChStatusUnit1:                  { class: 'E' },

	nO_DsCombinationTpsTc:               { class: 'E' },
	nO_UsCombinationTpsTc:               { class: 'E' },
	xdsl2LineStatusXtuTransSys:          { class: 'E' },
	xdsl2LineStatusInitResult:           { class: 'E' },
	xdsl2LineStatusAttainableRateDs:     { class: 'M', signed: false, div: 1, unit: 'kbit/s' },
	xdsl2LineStatusAttainableRateUs:     { class: 'M', signed: false, div: 1, unit: 'kbit/s' },
	xdsl2LineStatusActAtpDs:             { class: 'M', signed: true, div: 10, unit: 'dBm' },
	xdsl2LineStatusActAtpUs:             { class: 'M', signed: true, div: 10, unit: 'dBm' },
	xdsl2LineStatusActProfile:           { class: 'E' },
	xdsl2LineStatusActSnrModeDs:         { class: 'E' },
	xdsl2LineStatusActSnrModeUs:         { class: 'E' },
	xdsl2LineStatusTrellisDs:            { class: 'E' },
	xdsl2LineStatusTrellisUs:            { class: 'E' },
	xdsl2LineBandStatusLnAtten0:         { class: 'M', signed: false, div: 10, unit: 'dB' },
	xdsl2LineBandStatusSigAtten0:        { class: 'M', signed: false, div: 10, unit: 'dB' },
	xdsl2LineBandStatusLnAtten1:         { class: 'M', signed: false, div: 10, unit: 'dB' },
	xdsl2LineBandStatusSigAtten1:        { class: 'M', signed: false, div: 10, unit: 'dB' },
	xdsl2LineBandStatusLnAtten2:         { class: 'M', signed: false, div: 10, unit: 'dB' },
	xdsl2LineBandStatusSigAtten2:        { class: 'M', signed: false, div: 10, unit: 'dB' },
	xdsl2LineBandStatusLnAtten3:         { class: 'M', signed: false, div: 10, unit: 'dB' },
	xdsl2LineBandStatusSigAtten3:        { class: 'M', signed: false, div: 10, unit: 'dB' },
	xdsl2LineBandStatusLnAtten4:         { class: 'M', signed: false, div: 10, unit: 'dB' },
	xdsl2LineBandStatusSigAtten4:        { class: 'M', signed: false, div: 10, unit: 'dB' },
	xdsl2LineBandStatusLnAtten10:        { class: 'M', signed: false, div: 10, unit: 'dB' },
	xdsl2LineBandStatusSigAtten10:       { class: 'M', signed: false, div: 10, unit: 'dB' },
	xdsl2LineBandStatusSnrMargin9:       { class: 'M', signed: true, div: 10, unit: 'dB' },
	xdsl2LineBandStatusSnrMargin10:      { class: 'M', signed: true, div: 10, unit: 'dB' },
	xdsl2MetanoiaRtFailureReasons:       { class: 'E' },

	xdsl2ChStatusActDataRate0:           { class: 'M', signed: false, div: 1, unit: 'kbit/s' },
	xdsl2ChStatusActDelay0:              { class: 'M', signed: false, div: 1, unit: 'ms' },
	xdsl2ChStatusActInp0:                { class: 'M', signed: false, div: 10, unit: 'symbols' },
	xdsl2ChStatusActDataRate2:           { class: 'M', signed: false, div: 1, unit: 'kbit/s' },
	xdsl2ChStatusActDelay2:              { class: 'M', signed: false, div: 1, unit: 'ms' },
	xdsl2ChStatusActInp2:                { class: 'M', signed: false, div: 10, unit: 'symbols' },

	xdslMetanoiaShowtimeSeconds:         { class: 'C' },
	xdslMetanoiaRtCurrCodingViolations0: { class: 'C' },
	xdslMetanoiaRtCurrCorrectedBlocks0:  { class: 'C' },
	xdslMetanoiaRtCurrCodingViolations1: { class: 'C' },
	xdslMetanoiaRtCurrCorrectedBlocks1:  { class: 'C' },
};

// 24-bit two's complement (7.2).
export function signed24(word) {
	return (word & SIGN_BIT) ? word - (1 << WORD_BITS) : word;
};

// Whether a word is a special value (7.3) of a signed or unsigned register.
export function is_special(word, signed) {
	return (word in SPECIAL) || (!signed && word == INVALID);
};

// Value of a measurement register (class M), or null for a special value.
export function measurement(word, fmt) {
	if (is_special(word, fmt.signed))
		return null;

	const value = fmt.signed ? signed24(word) : word;

	// Dividing two integers truncates in ucode; values in whole units stay integers.
	return fmt.div == 1 ? value : value / (fmt.div * 1.0);
};

// Increase of a counter between two reads; counters wrap at 2^24 (7.2).
export function counter_delta(previous, current) {
	return (current - previous) & WORD_MASK;
};

// Value of a 48-bit counter split into two words (7.2).
export function combine48(hi, lo) {
	return (hi << WORD_BITS) | lo;
};

// Names of all registers with a format.
export function names() {
	return sort(keys(FORMATS));
};

export function format(name) {
	const fmt = FORMATS[name];

	if (fmt == null)
		die(`no format for register ${name}`);

	return fmt;
};

// Identification and enumerations (9.2 to 9.4). Enumerations return
// { value, name }; name is null for values the specification does not list,
// which are reported as numbers (7.3).

const LINE_STATES = [ 'idle', 'handshake', 'training', 'showtime' ];

const FAILURE_REASONS = [
	'none', 'loss_of_signal', 'loss_of_power', 'crc_errors', 'training_failure',
	'disconnect', 'snr_below_minimum',
];

const PROFILES = [ '8a', '8b', '8c', '8d', '12a', '12b', '17a', '30a' ];

const TPS_TC = { [0x20]: 'PTM', [0x40]: 'ATM', [0x80]: 'STM' };

const SNR_MODES = [ null, 'disabled', 'enabled' ];

const INIT_RESULTS = [
	'noFail', 'configError', 'configNotFeasible', 'commFail', 'noPeerAtu', 'otherCause',
];

// Bits of Xdsl2TransmissionModeType (RFC 5650).
const TRANSMISSION_MODES = [
	'ansit1413', 'etsi', 'g9921PotsNonOverlapped', 'g9921PotsOverlapped',
	'g9921IsdnNonOverlapped', 'g9921isdnOverlapped', 'g9921tcmIsdnNonOverlapped',
	'g9921tcmIsdnOverlapped', 'g9922potsNonOverlapped', 'g9922potsOverlapped',
	'g9922tcmIsdnNonOverlapped', 'g9922tcmIsdnOverlapped', 'g9921tcmIsdnSymmetric',
	'reserved1', 'reserved2', 'reserved3', 'reserved4', 'reserved5',
	'g9923PotsNonOverlapped', 'g9923PotsOverlapped', 'g9923IsdnNonOverlapped',
	'g9923isdnOverlapped', 'reserved6', 'reserved7', 'g9924potsNonOverlapped',
	'g9924potsOverlapped', 'reserved8', 'reserved9', 'g9923AnnexIAllDigNonOverlapped',
	'g9923AnnexIAllDigOverlapped', 'g9923AnnexJAllDigNonOverlapped',
	'g9923AnnexJAllDigOverlapped', 'g9924AnnexIAllDigNonOverlapped',
	'g9924AnnexIAllDigOverlapped', 'g9923AnnexLMode1NonOverlapped',
	'g9923AnnexLMode2NonOverlapped', 'g9923AnnexLMode3Overlapped',
	'g9923AnnexLMode4Overlapped', 'g9923AnnexMPotsNonOverlapped',
	'g9923AnnexMPotsOverlapped', 'g9925PotsNonOverlapped', 'g9925PotsOverlapped',
	'g9925IsdnNonOverlapped', 'g9925isdnOverlapped', 'reserved10', 'reserved11',
	'g9925AnnexIAllDigNonOverlapped', 'g9925AnnexIAllDigOverlapped',
	'g9925AnnexJAllDigNonOverlapped', 'g9925AnnexJAllDigOverlapped',
	'g9925AnnexMPotsNonOverlapped', 'g9925AnnexMPotsOverlapped', 'reserved12',
	'reserved13', 'reserved14', 'reserved15', 'g9932AnnexA', 'g9932AnnexB',
	'g9932AnnexC', 'reserved16', 'reserved17', 'reserved18', 'reserved19', 'reserved20',
];

// Standard and common name per prefix of a transmission mode.
const STANDARDS = {
	ansit1413: [ 'ANSI T1.413', 'ADSL' ],
	etsi: [ 'ETSI TS 101 388', 'ADSL' ],
	g9921: [ 'G.992.1', 'ADSL' ],
	g9922: [ 'G.992.2', 'ADSL' ],
	g9923: [ 'G.992.3', 'ADSL2' ],
	g9924: [ 'G.992.4', 'ADSL2' ],
	g9925: [ 'G.992.5', 'ADSL2+' ],
	g9932: [ 'G.993.2', 'VDSL2' ],
};

function enumeration(table, word) {
	return { value: word, name: table[word] ?? null };
}

// Six decimal digits of a BCD word, or null if a nibble is not a digit.
function bcd_digits(word) {
	const digits = sprintf('%06x', word);

	return match(digits, /^[0-9]{6}$/) ? digits : null;
}

// Firmware identification (9.2.3) from the result of layout.parse_id().
export function firmware(id) {
	const date = bcd_digits(id.date);	// MMDDYY
	const time = bcd_digits(id.time);	// hhmmss

	return {
		version: id.version,
		major: id.version >> 16,
		minor: id.version & 0xffff,
		date: date ? `20${substr(date, 4, 2)}-${substr(date, 0, 2)}-${substr(date, 2, 2)}` : null,
		time: time ? `${substr(time, 0, 2)}:${substr(time, 2, 2)}:${substr(time, 4, 2)}` : null,
	};
};

// xdslTerminal (9.2.1).
export function terminal(word) {
	const state = (word >> 8) & 3;
	let chip;

	if (word & 0x40)
		chip = (word & 0x08) ? 'BARTON' : 'BORA';
	else
		chip = (word & 0x08) ? 'AURORA' : 'ARGO';

	return {
		role: (word & 1) ? 'RT' : 'OT',
		chip,
		line_state: LINE_STATES[state],
		showtime: state == 3,
	};
};

// Cause of the last loss of showtime (9.4).
export function failure_reason(word) {
	return enumeration(FAILURE_REASONS, word);
};

// Active transmission mode, given as bit number (9.3.2). Outside showtime the
// register holds 0, which the caller must not report as T1.413.
export function trans_sys(word) {
	const name = TRANSMISSION_MODES[word];

	if (name == null || index(name, 'reserved') == 0)
		return { value: word, name: null, standard: null, annex: null, family: null };

	const standard = STANDARDS[match(name, /^(ansit1413|etsi|g99[0-9]{2})/)[1]];
	let annex = match(name, /Annex([A-Z])/)?.[1];

	if (annex == null) {
		if (match(name, /[Pp]ots/))
			annex = 'A';
		else if (match(name, /tcmIsdn/))
			annex = 'C';
		else if (match(name, /[Ii]sdn/))
			annex = 'B';
	}

	return { value: word, name, standard: standard[0], annex, family: standard[1] };
};

// Active VDSL2 profile (9.3.3): exactly one of bits 0-7 is set.
export function profile(word) {
	for (let i = 0; i < length(PROFILES); i++)
		if (word == (1 << i))
			return { value: word, name: PROFILES[i] };

	return { value: word, name: null };
};

// TPS-TC of a direction (9.3.4).
export function tps_tc(word) {
	return enumeration(TPS_TC, word);
};

// TruthValue (9.3.5): 1 true, 2 false.
export function truth(word) {
	return word == 1 ? true : word == 2 ? false : null;
};

// Virtual noise mode in use (9.3.5).
export function snr_mode(word) {
	return enumeration(SNR_MODES, word);
};

// Result of the last full initialisation (9.3.5).
export function init_result(word) {
	return enumeration(INIT_RESULTS, word);
};

// Decoders of the registers of class E and I that have one.
const DECODERS = {
	xdslTerminal: terminal,
	xdsl2MetanoiaRtFailureReasons: failure_reason,
	xdsl2LineStatusXtuTransSys: trans_sys,
	xdsl2LineStatusActProfile: profile,
	nO_DsCombinationTpsTc: tps_tc,
	nO_UsCombinationTpsTc: tps_tc,
	xdsl2LineStatusTrellisDs: truth,
	xdsl2LineStatusTrellisUs: truth,
	xdsl2LineStatusActSnrModeDs: snr_mode,
	xdsl2LineStatusActSnrModeUs: snr_mode,
	xdsl2LineStatusInitResult: init_result,
};

// Decodes the words of a register according to its value class.
export function decode(name, words) {
	const fmt = format(name);

	if (fmt.class == 'M')
		return measurement(words[0], fmt);

	if (DECODERS[name])
		return DECODERS[name](length(words) == 1 ? words[0] : words);

	return length(words) == 1 ? words[0] : words;
};
