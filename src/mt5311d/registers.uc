// Registers of the DSP memory used by the daemon (MT5311_EBM_Monitoring_Spec.md,
// Appendix A). All registers are in space X. Their addresses depend on the address
// layout of the firmware (8.1); layout.uc selects it.

'use strict';

export const LAYOUT_160 = '1.60';
export const LAYOUT_161 = '1.61';

const LAYOUT_INDEX = { [LAYOUT_160]: 0, [LAYOUT_161]: 1 };

// name: [ address in layout 1.60, address in layout 1.61, words ]
const REGISTERS = {
	// Identification and system (A.1, 8.2)
	ModemStatus:                         [ 0x00001d, 0x00001d, 1 ],
	xdslFirmwareVer:                     [ 0x006c31, 0x006c31, 1 ],
	xdslFirmwareDate:                    [ 0x006c32, 0x006c32, 1 ],
	xdslFirmwareTime:                    [ 0x006c33, 0x006c33, 1 ],
	xdslBoardType:                       [ 0x006c34, 0x006c34, 1 ],
	xdslTerminal:                        [ 0x006c35, 0x006c35, 1 ],
	xdslMetanoiaSignature:               [ 0x006c36, 0x006c36, 1 ],

	// Layout check constants (8.2)
	xdsl2LineBand6:                      [ 0x006fef, 0x007004, 1 ],
	xdsl2LineBand7:                      [ 0x006ff3, 0x007008, 1 ],
	xdsl2LineBand8:                      [ 0x006ff7, 0x00700c, 1 ],
	xdsl2LineBand9:                      [ 0x006ffb, 0x007010, 1 ],
	xdsl2LineBand10:                     [ 0x006fff, 0x007014, 1 ],
	xdsl2ChStatusUnit0:                  [ 0x007003, 0x007018, 1 ],
	xdsl2ChStatusUnit1:                  [ 0x007011, 0x007026, 1 ],

	// Line status (A.2)
	nO_DsCombinationTpsTc:               [ 0x001778, 0x001775, 1 ],
	nO_UsCombinationTpsTc:               [ 0x001779, 0x001776, 1 ],
	xdsl2LineStatusXtuTransSys:          [ 0x006f19, 0x006f2e, 1 ],
	xdsl2LineStatusInitResult:           [ 0x006f1b, 0x006f30, 1 ],
	xdsl2LineStatusAttainableRateDs:     [ 0x006f20, 0x006f35, 1 ],
	xdsl2LineStatusAttainableRateUs:     [ 0x006f21, 0x006f36, 1 ],
	xdsl2LineStatusActAtpDs:             [ 0x006f24, 0x006f39, 1 ],
	xdsl2LineStatusActAtpUs:             [ 0x006f25, 0x006f3a, 1 ],
	xdsl2LineStatusActProfile:           [ 0x006f26, 0x006f3b, 1 ],
	xdsl2LineStatusActSnrModeDs:         [ 0x006f2d, 0x006f42, 1 ],
	xdsl2LineStatusActSnrModeUs:         [ 0x006f2e, 0x006f43, 1 ],
	xdsl2LineStatusTrellisDs:            [ 0x006fd2, 0x006fe7, 1 ],
	xdsl2LineStatusTrellisUs:            [ 0x006fd3, 0x006fe8, 1 ],
	xdsl2LineBandStatusLnAtten0:         [ 0x006fd8, 0x006fed, 1 ],
	xdsl2LineBandStatusSigAtten0:        [ 0x006fd9, 0x006fee, 1 ],
	xdsl2LineBandStatusLnAtten1:         [ 0x006fdc, 0x006ff1, 1 ],
	xdsl2LineBandStatusSigAtten1:        [ 0x006fdd, 0x006ff2, 1 ],
	xdsl2LineBandStatusLnAtten2:         [ 0x006fe0, 0x006ff5, 1 ],
	xdsl2LineBandStatusSigAtten2:        [ 0x006fe1, 0x006ff6, 1 ],
	xdsl2LineBandStatusLnAtten3:         [ 0x006fe4, 0x006ff9, 1 ],
	xdsl2LineBandStatusSigAtten3:        [ 0x006fe5, 0x006ffa, 1 ],
	xdsl2LineBandStatusLnAtten4:         [ 0x006fe8, 0x006ffd, 1 ],
	xdsl2LineBandStatusSigAtten4:        [ 0x006fe9, 0x006ffe, 1 ],
	xdsl2LineBandStatusLnAtten10:        [ 0x007000, 0x007015, 1 ],
	xdsl2LineBandStatusSigAtten10:       [ 0x007001, 0x007016, 1 ],
	xdsl2LineBandStatusSnrMargin9:       [ 0x006ffe, 0x007013, 1 ],
	xdsl2LineBandStatusSnrMargin10:      [ 0x007002, 0x007017, 1 ],
	xdsl2MetanoiaRtFailureReasons:       [ 0x007f59, 0x007f6e, 1 ],

	// Channel status (A.3)
	xdsl2ChStatusActDataRate0:           [ 0x007004, 0x007019, 1 ],
	xdsl2ChStatusActDelay0:              [ 0x007006, 0x00701b, 1 ],
	xdsl2ChStatusActInp0:                [ 0x007007, 0x00701c, 1 ],
	xdsl2ChStatusActDataRate2:           [ 0x007020, 0x007035, 1 ],
	xdsl2ChStatusActDelay2:              [ 0x007022, 0x007037, 1 ],
	xdsl2ChStatusActInp2:                [ 0x007023, 0x007038, 1 ],

	// Counters of the xTU-R (A.5, 9.1)
	xdslMetanoiaShowtimeSeconds:         [ 0x006d35, 0x006d35, 1 ],
	xdslMetanoiaRtCurrCodingViolations0: [ 0x007f28, 0x007f3d, 1 ],
	xdslMetanoiaRtCurrCorrectedBlocks0:  [ 0x007f27, 0x007f3c, 1 ],
	xdslMetanoiaRtCurrCodingViolations1: [ 0x007f46, 0x007f5b, 1 ],
	xdslMetanoiaRtCurrCorrectedBlocks1:  [ 0x007f45, 0x007f5a, 1 ],
};

function lookup(name) {
	const reg = REGISTERS[name];

	if (reg == null)
		die(`unknown register ${name}`);

	return reg;
}

// Address of a register in a layout.
export function address(layout, name) {
	const index = LAYOUT_INDEX[layout];

	if (index == null)
		die(`unknown layout ${layout}`);

	return lookup(name)[index];
};

// Number of words of a register.
export function words(name) {
	return lookup(name)[2];
};

export function names() {
	return sort(keys(REGISTERS));
};
