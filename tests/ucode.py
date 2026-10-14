"""Runs ucode code from tests and returns its result.

ucode runs in the OpenWrt test container (tests/container), which has the
repository mounted read-only at CONTAINER_REPO. Code under test prints exactly
one JSON value (printf('%J', …)), which is parsed and returned. Binary data does
not survive JSON; pass and return it hex-encoded (hexenc()/hexdec() in ucode).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

CONTAINER_REPO = PurePosixPath("/mt5311d")

# Runs a command in the container: argv -> (exit code, stdout, stderr).
Executor = Callable[[list[str]], tuple[int, str, str]]

_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


def container_path(path: Path | str) -> PurePosixPath:
    """Path of a file of the repository inside the container."""
    return CONTAINER_REPO / Path(path).resolve().relative_to(REPO).as_posix()


class UcodeError(Exception):
    """ucode failed, or its output was not a JSON value."""

    def __init__(self, message: str, returncode: int | None = None, stderr: str = "") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class Ucode:
    """Runs the ucode interpreter with module search paths for the code under test.

    Search paths are given as paths of the repository and mapped into the container.
    """

    def __init__(self, execute: Executor,
                 search_paths: Sequence[Path] = (SRC / "*.uc",)) -> None:
        self.execute = execute
        self.search_paths = [str(container_path(p.parent) / p.name) for p in search_paths]

    def run(self, source: str, **globals: Any) -> Any:
        """Runs source; keyword arguments become global variables (as JSON)."""
        args = ["-D", json.dumps(globals)] if globals else []
        stdout = self._exec([*args, "-e", source])
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as e:
            raise UcodeError(f"ucode output is not a JSON value: {stdout!r}") from e

    def run_script(self, path: Path, *args: str) -> str:
        """Runs a script of the repository with command line arguments; returns stdout."""
        return self._exec([str(container_path(path)), *args])

    def call(self, module: str, function: str, *args: Any) -> Any:
        """Calls an exported function of a module with JSON arguments."""
        if not _MODULE_NAME.match(module):
            raise ValueError(f"invalid module name {module!r}")
        source = (f"import * as m from '{module}';\n"
                  f"printf('%J', m[{json.dumps(function)}](...ARGS));")
        return self.run(source, ARGS=list(args))

    def compile(self, path: Path, *, module: bool = False) -> None:
        """Checks a program, or a module with exports, for syntax errors.

        A program is compiled without running it. A module is imported, which
        compiles it and runs only its top-level definitions; the ucode version of
        OpenWrt 25.12 has no flag to compile a module on its own.

        Raises UcodeError on syntax errors.
        """
        target = str(container_path(path))
        if module:
            self._exec(["-e", f"import * as m from {json.dumps(target)};"])
        else:
            self._exec(["-c", "-o", "/dev/null", target])

    def _exec(self, args: list[str]) -> str:
        cmd = ["ucode"]
        for pattern in self.search_paths:
            cmd += ["-L", pattern]
        returncode, stdout, stderr = self.execute([*cmd, *args])
        if returncode != 0:
            raise UcodeError(f"ucode exited with {returncode}:\n{stderr.strip()}",
                             returncode, stderr)
        return stdout
