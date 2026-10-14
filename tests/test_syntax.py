"""Compiles every ucode file under src/ and tools/ to catch syntax errors early.

Files directly in src/ and in tools/ are programs (e.g. src/mt5311d.uc), files in
subdirectories of src/ are modules (src/mt5311d/*.uc).
"""

import pytest

from ucode import REPO, SRC

TOOLS = REPO / "tools"
SOURCES = sorted(p for d in (SRC, TOOLS) if d.is_dir() for p in d.rglob("*.uc"))


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(REPO)))
def test_compiles(ucode, path):
    ucode.compile(path, module=path.parent.parent == SRC)
