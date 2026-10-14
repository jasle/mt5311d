"""Runs ucode code from tests and returns its result.

Code under test prints exactly one JSON value (printf('%J', …)), which is parsed
and returned. Binary data does not survive JSON; pass and return it hex-encoded
(hexenc()/hexdec() in ucode).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


class UcodeError(Exception):
    """ucode failed, or its output was not a JSON value."""

    def __init__(self, message: str, returncode: int | None = None, stderr: str = "") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class Ucode:
    """Runs the ucode interpreter with module search paths for the code under test."""

    def __init__(self, binary: str = "ucode",
                 search_paths: Sequence[Path | str] = (SRC / "*.uc",)) -> None:
        self.binary = binary
        self.search_paths = [str(p) for p in search_paths]

    def run(self, source: str, **globals: Any) -> Any:
        """Runs source; keyword arguments become global variables (as JSON)."""
        args = ["-D", json.dumps(globals)] if globals else []
        stdout = self._exec([*args, "-e", source])
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as e:
            raise UcodeError(f"ucode output is not a JSON value: {stdout!r}") from e

    def call(self, module: str, function: str, *args: Any) -> Any:
        """Calls an exported function of a module with JSON arguments."""
        if not _MODULE_NAME.match(module):
            raise ValueError(f"invalid module name {module!r}")
        source = (f"import * as m from '{module}';\n"
                  f"printf('%J', m[{json.dumps(function)}](...ARGS));")
        return self.run(source, ARGS=list(args))

    def compile(self, path: Path | str, *, module: bool = False) -> None:
        """Checks a program, or a module with exports, for syntax errors.

        A program is compiled without running it. A module is imported, which
        compiles it and runs only its top-level definitions; the ucode version of
        OpenWrt 25.12 has no flag to compile a module on its own.

        Raises UcodeError on syntax errors.
        """
        if module:
            path = Path(path).resolve()
            self._exec(["-e", f"import * as m from {json.dumps(str(path))};"])
        else:
            self._exec(["-c", "-o", os.devnull, str(path)])

    def _exec(self, args: list[str]) -> str:
        cmd = [self.binary]
        for pattern in self.search_paths:
            cmd += ["-L", pattern]
        # surrogateescape keeps bytes that are not valid UTF-8 visible in errors.
        result = subprocess.run([*cmd, *args], capture_output=True, text=True,
                                errors="surrogateescape", check=False)
        if result.returncode != 0:
            raise UcodeError(f"ucode exited with {result.returncode}:\n{result.stderr.strip()}",
                             result.returncode, result.stderr)
        return result.stdout
