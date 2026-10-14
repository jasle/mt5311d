from pathlib import Path

import pytest

from ucode import Ucode, UcodeError

FIXTURES = Path(__file__).parent / "fixtures" / "ucode"


@pytest.fixture
def demo(execute) -> Ucode:
    return Ucode(execute, search_paths=(FIXTURES / "*.uc",))


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("printf('%J', 42);", 42),
        ("printf('%J', 'abc');", "abc"),
        ("printf('%J', [ 1, [ 2 ] ]);", [1, [2]]),
        ("printf('%J', { a: 1, b: null });", {"a": 1, "b": None}),
        ("printf('%J', null);", None),
    ],
)
def test_run_returns_json(ucode, source, expected):
    assert ucode.run(source) == expected


def test_run_passes_globals(ucode):
    assert ucode.run("printf('%J', [ A, B ]);", A=1, B={"x": [True]}) == [1, {"x": [True]}]


def test_call_uses_the_search_path(demo):
    assert demo.call("demo.calc", "add", 2, 3) == 5
    assert demo.call("demo.calc", "describe", [1, "a"]) == {"type": "array", "value": [1, "a"]}


def test_call_validates_the_module_name(demo):
    with pytest.raises(ValueError):
        demo.call("demo.calc'; die('x'); '", "add")


def test_unknown_module(demo):
    with pytest.raises(UcodeError, match="Unable to resolve path for module 'demo.nope'"):
        demo.call("demo.nope", "add")


def test_die_raises_with_message(demo):
    with pytest.raises(UcodeError, match="kaputt") as e:
        demo.call("demo.calc", "fail", "kaputt")
    assert e.value.returncode != 0


def test_syntax_error(ucode):
    with pytest.raises(UcodeError, match="Syntax error"):
        ucode.run("let x = ;")


def test_output_must_be_json(ucode):
    with pytest.raises(UcodeError, match="not a JSON value"):
        ucode.run("print('no json');")


def test_binary_data_as_hex(ucode):
    assert ucode.run("printf('%J', hexenc(hexdec(DATA) + '\\x01'));", DATA="00ff") == "00ff01"


def test_compile(ucode):
    ucode.compile(FIXTURES / "syntax" / "program.uc")
    ucode.compile(FIXTURES / "syntax" / "module.uc", module=True)
    with pytest.raises(UcodeError, match="Syntax error"):
        ucode.compile(FIXTURES / "syntax" / "broken.uc")
    with pytest.raises(UcodeError, match="Syntax error"):
        ucode.compile(FIXTURES / "syntax" / "broken.uc", module=True)
