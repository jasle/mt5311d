// Module used by the tests of the ucode runner (tests/test_ucode_runner.py).

'use strict';

export function add(a, b) {
	return a + b;
};

export function describe(value) {
	return { type: type(value), value };
};

export function fail(message) {
	die(message);
};
