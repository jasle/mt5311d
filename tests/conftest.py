import os
import shutil

import pytest

from ucode import Ucode


@pytest.fixture(scope="session")
def ucode_binary() -> str:
    binary = os.environ.get("UCODE", "ucode")
    if shutil.which(binary) is None:
        pytest.fail(f"ucode interpreter {binary!r} not found; install ucode or set UCODE",
                    pytrace=False)
    return binary


@pytest.fixture(scope="session")
def ucode(ucode_binary) -> Ucode:
    """Runs ucode with the modules from src/ on the search path."""
    return Ucode(ucode_binary)
