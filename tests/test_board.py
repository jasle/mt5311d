"""Tests of src/mt5311d/board.uc on files in the container."""

import pytest

# Writes BOARD (if not null) to PATH, runs the operation and returns its result,
# the file afterwards and whether the file is still the same inode.
DRIVER = """
    import * as fs from 'fs';
    import * as board from 'mt5311d.board';

    fs.unlink(PATH);
    if (BOARD != null)
        fs.writefile(PATH, sprintf('%J', BOARD));

    const before = fs.stat(PATH)?.inode;
    const result = OPERATION == 'add' ? board.add(PATH, MODEM) : board.remove(PATH);
    const text = fs.readfile(PATH);

    printf('%J', {
        result,
        board: text != null ? json(text) : null,
        same_inode: before != null && before == fs.stat(PATH)?.inode,
        temporary_left: fs.stat(PATH + '.mt5311d') != null,
    });
"""

PATH = "/tmp/board.json"
NETWORK = {"model": {"id": "test,board", "name": "Test"}, "network": {"wan": {"device": "eth1"}}}
VDSL = {"type": "vdsl"}
OURS = {"type": "vdsl", "managed_by": "mt5311d"}
FOREIGN = {"type": "vdsl", "annex": "b", "tone": "av", "xfer_mode": "ptm"}


@pytest.fixture
def run(ucode):
    def run(operation, board, modem=None):
        return ucode.run(DRIVER, PATH=PATH, BOARD=board, OPERATION=operation, MODEM=modem)

    return run


def test_add(run):
    result = run("add", NETWORK, VDSL)
    assert result["result"] == "changed"
    assert result["board"] == {**NETWORK, "dsl": {"modem": OURS}}
    assert result["temporary_left"] is False


def test_add_keeps_other_dsl_fields(run):
    board = {**NETWORK, "dsl": {"atmbridge": {"vpi": 1}}}
    result = run("add", board, VDSL)
    assert result["board"]["dsl"] == {"atmbridge": {"vpi": 1}, "modem": OURS}


def test_add_unchanged_does_not_write(run):
    result = run("add", {**NETWORK, "dsl": {"modem": OURS}}, VDSL)
    assert result["result"] == "unchanged"
    assert result["same_inode"] is True


def test_add_updates_our_entry(run):
    result = run("add", {**NETWORK, "dsl": {"modem": OURS}}, {"type": "vdsl", "annex": "b"})
    assert result["result"] == "changed"
    assert result["board"]["dsl"]["modem"] == {"type": "vdsl", "annex": "b",
                                               "managed_by": "mt5311d"}


def test_add_leaves_a_foreign_entry(run):
    board = {**NETWORK, "dsl": {"modem": FOREIGN}}
    result = run("add", board, VDSL)
    assert result["result"] == "foreign"
    assert result["board"] == board
    assert result["same_inode"] is True


def test_remove(run):
    result = run("remove", {**NETWORK, "dsl": {"modem": OURS}})
    assert result["result"] == "changed"
    assert result["board"] == NETWORK


def test_remove_keeps_other_dsl_fields(run):
    result = run("remove", {**NETWORK, "dsl": {"modem": OURS, "atmbridge": {"vpi": 1}}})
    assert result["board"]["dsl"] == {"atmbridge": {"vpi": 1}}


def test_remove_leaves_a_foreign_entry(run):
    board = {**NETWORK, "dsl": {"modem": FOREIGN}}
    result = run("remove", board)
    assert result["result"] == "foreign"
    assert result["board"] == board


def test_remove_without_entry(run):
    result = run("remove", NETWORK)
    assert result["result"] == "unchanged"
    assert result["same_inode"] is True


@pytest.mark.parametrize("operation", ["add", "remove"])
def test_missing_file_is_not_created(run, operation):
    result = run(operation, None, VDSL)
    assert result["result"].startswith("/tmp/board.json: ")
    assert result["board"] is None
