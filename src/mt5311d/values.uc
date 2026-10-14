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

	xdsl2LineStatusAttainableRateDs:     { class: 'M', signed: false, div: 1, unit: 'kbit/s' },
	xdsl2LineStatusAttainableRateUs:     { class: 'M', signed: false, div: 1, unit: 'kbit/s' },
	xdsl2LineStatusActAtpDs:             { class: 'M', signed: true, div: 10, unit: 'dBm' },
	xdsl2LineStatusActAtpUs:             { class: 'M', signed: true, div: 10, unit: 'dBm' },
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

// Decodes the words of a register according to its value class.
export function decode(name, words) {
	const fmt = format(name);

	if (fmt.class == 'M')
		return measurement(words[0], fmt);

	return length(words) == 1 ? words[0] : words;
};
