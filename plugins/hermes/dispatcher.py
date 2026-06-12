# SPDX-License-Identifier: AGPL-3.0-or-later
"""Thin Python wrapper around the bash dispatcher at bin/clermes.

The bash dispatcher is the operationally-tested layer. This module shells
out to it and parses results. It does not duplicate dispatcher logic.

Path resolution honors $CLERMES_HOME, defaulting to ~/.clermes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from clermes.config import clermes_home
from clermes.registry import worker_names  # noqa: F401 (re-exported via dispatcher.worker_names)


def dispatcher_bin() -> Path:
    """Return the path to the bash dispatcher binary."""
    candidate = clermes_home() / "clermes"
    if candidate.exists() and os.access(candidate, os.X_OK):
        return candidate
    resolved = shutil.which("clermes")
    if resolved:
        return Path(resolved)
    raise FileNotFoundError(
        f"clermes dispatcher not found at {candidate} or on PATH. "
        "Run install.sh from the clermes repo."
    )


@dataclass
class DispatcherResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
        }


def run(args: List[str], timeout: int = 60) -> DispatcherResult:
    """Invoke the dispatcher with the given subcommand args."""
    cmd = [str(dispatcher_bin()), *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return DispatcherResult(
            ok=False,
            stdout=exc.stdout or "",
            stderr=f"dispatcher timed out after {timeout}s",
            returncode=124,
        )
    return DispatcherResult(
        ok=proc.returncode == 0,
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
    )


def snapshot() -> Dict[str, Any]:
    """Run `clermes snapshot` and return parsed JSON."""
    result = run(["snapshot"], timeout=30)
    if not result.ok:
        return {"error": result.stderr or "snapshot failed", "raw": result.stdout}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {"error": f"snapshot returned non-JSON: {exc}", "raw": result.stdout}


def list_workers() -> str:
    return run(["list"], timeout=15).stdout


def send(worker: str, prompt: str, timeout: int = 30) -> DispatcherResult:
    return run(["send", worker, prompt], timeout=timeout)


def capture(worker: str, lines: int = 80) -> str:
    return run(["capture", worker, str(lines)], timeout=15).stdout


def heal() -> str:
    return run(["heal"], timeout=120).stdout


def spawn(worker: str) -> DispatcherResult:
    return run(["spawn", worker], timeout=60)
