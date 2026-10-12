"""Rule files, rule routing and the file-op check, ported from hooks/inject.js.

ruleTargetFor and fileOpReason live in inject.js; tests/fileops.json holds the
two implementations of the file-op check to the same answers.
"""

import os
import re
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parent.parent / "hooks" / "rules"
NOT_IN_AUTO = "<!-- curt: not-in-auto -->"
ONLY_IN_AUTO = "<!-- curt: only-in-auto -->"
_IGNORE_LINE = re.compile(r"^<!-- anti-slop:.*$", re.M)

CODE_EXT = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".c",
    ".h", ".cc", ".cpp", ".cs", ".php", ".swift", ".scala", ".rb", ".sh",
    ".bash", ".zsh", ".sql", ".lua", ".hs", ".ipynb",
}
PROSE_EXT = {".md", ".mdx", ".rst", ".txt", ".adoc"}
COMMIT_FILES = {"COMMIT_EDITMSG", "MERGE_MSG", "TAG_EDITMSG"}
_GIT_COMMIT = re.compile(r"\bgit\b[^\n]*\bcommit\b")

_GUARD_EXT = "|".join(sorted(e[1:] for e in CODE_EXT | PROSE_EXT))
_FILE = rf"[^\s|&;<>()\"']*\.(?:{_GUARD_EXT})\b"
_IN_PLACE = (re.compile(r"\bsed\b[^|&;]*\s-[a-z]*i\b"), re.compile(r"\bperl\b[^|&;]*\s-[a-z]*i\b"))
_REDIRECT = re.compile(rf">>?\s*{_FILE}")
_TEE = re.compile(rf"\btee\b[^|&;]*\s{_FILE}")
_READ = re.compile(rf"\b(?:cat|head|tail)\b[^|&;]*\s{_FILE}")

# Hermes's file tools, not Claude Code's: the model retries with the tool named here.
HERMES_REASON = {
    "in_place": "use the patch tool for an in-place change instead of sed -i.",
    "redirect": "use write_file or patch to change a file instead of a shell redirect.",
    "tee": "use write_file to create a file instead of tee.",
    "read": "use read_file to read a file instead of cat, head, or tail.",
}


def read_rule(name: str, auto: bool) -> str | None:
    try:
        text = (RULES_DIR / f"{name}.md").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    lines = [
        line for line in text.split("\n")
        if not (auto and NOT_IN_AUTO in line) and (auto or ONLY_IN_AUTO not in line)
    ]
    text = "\n".join(lines).replace(NOT_IN_AUTO, "").replace(ONLY_IN_AUTO, "")
    return _IGNORE_LINE.sub("", text).strip()


def rule_target(tool_name: str | None, args: object) -> str | None:
    args = args if isinstance(args, dict) else {}
    if tool_name == "terminal" and _GIT_COMMIT.search(str(args.get("command") or "")):
        return "commit"
    if tool_name in ("write_file", "patch"):
        path = str(args.get("path") or "")
        if os.path.basename(path) in COMMIT_FILES:
            return "commit"
        ext = os.path.splitext(path)[1].lower()
        if ext in PROSE_EXT:
            return "prose"
        if ext in CODE_EXT:
            return "code"
    return None


def file_op_reason(command: str | None) -> str | None:
    cmd = command or ""
    if any(p.search(cmd) for p in _IN_PLACE):
        return "in_place"
    if _REDIRECT.search(cmd):
        return "redirect"
    if _TEE.search(cmd):
        return "tee"
    if _READ.search(cmd):
        return "read"
    return None


def _approvals_mode() -> str:
    from hermes_cli.config import load_config_readonly
    return str((load_config_readonly().get("approvals") or {}).get("mode") or "")


def approvals_off() -> bool:
    """Hermes's counterpart of Claude Code's auto permission mode."""
    if os.environ.get("HERMES_YOLO_MODE"):
        return True
    try:
        return _approvals_mode().lower() == "off"
    except Exception:
        return False
