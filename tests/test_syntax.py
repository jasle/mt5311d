"""Compiles every ucode file under src/ to catch syntax errors early.

Files directly in src/ are programs (e.g. src/mt5311d.uc), files in its
subdirectories are modules (src/mt5311d/*.uc).
"""

import pytest

from ucode import SRC

SOURCES = sorted(SRC.rglob("*.uc")) if SRC.is_dir() else []


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(SRC)))
def test_compiles(ucode, path):
    ucode.compile(path, module=path.parent != SRC)
