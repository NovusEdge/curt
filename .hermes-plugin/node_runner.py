"""Run a Node script in --json mode and parse what it prints."""

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

TIMEOUT_S = 2.0
_warned_missing = False


def find_node() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    # The Hermes installer ships its own node, which is not always on PATH.
    try:
        hermes_home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    except RuntimeError:  # Path.home() when no home directory resolves
        return None
    bundled = hermes_home / "node" / "bin" / "node"
    return str(bundled) if bundled.is_file() else None


def run_json(script: Path, payload: dict) -> object | None:
    global _warned_missing
    node = find_node()
    if node is None:
        if not _warned_missing:
            logger.warning("curt: node not found; prose lint is off, rules and the guard still run")
            _warned_missing = True
        return None
    try:
        stdin = json.dumps(payload)
    except (TypeError, ValueError) as exc:
        logger.debug("curt: payload for %s is not JSON-serializable: %s", script.name, exc)
        return None
    try:
        # Explicit utf-8 with replacement: the locale codec would raise on stray bytes.
        done = subprocess.run(
            [node, str(script), "--json"], input=stdin, capture_output=True,
            encoding="utf-8", errors="replace", timeout=TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("curt: %s did not finish: %s", script.name, exc)
        return None
    if done.returncode != 0:
        logger.debug("curt: %s exited %s: %s", script.name, done.returncode, done.stderr.strip())
        return None
    try:
        return json.loads(done.stdout)
    except ValueError:
        logger.debug("curt: %s printed non-JSON output", script.name)
        return None
