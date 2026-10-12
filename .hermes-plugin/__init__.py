"""curt for Hermes Agent.

The Claude Code hooks map onto Hermes like this: SessionStart becomes a system
prompt section, UserPromptSubmit becomes pre_llm_call, PostToolUse becomes
on_interim_message plus transform_tool_result, and the PreToolUse guard becomes
pre_tool_call. Detection runs in hooks/check.js through node.
"""

import hashlib
import logging
import os
from pathlib import Path

from . import history, node_runner, report, rules

logger = logging.getLogger(__name__)

CHECK_JS = Path(__file__).resolve().parent.parent / "hooks" / "check.js"
# Hermes caps one plugin section at 4,000 characters and skips an empty one.
SECTION_MAX = 4000
REMIND_EVERY = int(os.environ.get("ANTI_SLOP_REMIND_EVERY") or 9)


class Session:
    def __init__(self):
        self.prompts = 0
        self.last_reported = None
        self.turn_id = ""
        self.user = {}
        self.interim = {}
        self.seen = {}
        self.injected = set()


# Hermes keeps plugins loaded for the life of the process, so state stays in
# memory instead of the temp files the Claude Code hook needs.
_sessions = {}


def session(session_id):
    return _sessions.setdefault(session_id or "", Session())


def _check(assistant_text, user_text):
    result = node_runner.run_json(CHECK_JS, {"assistant": assistant_text, "user": user_text})
    return [v for v in result if isinstance(v, dict)] if isinstance(result, list) else []


def _core():
    return rules.read_rule("core", rules.approvals_off()) or report.SHORT


def core_section(info):
    text = _core()
    return text if len(text) <= SECTION_MAX else ""


def _previous_report(s, previous_turn_id, conversation_history):
    user_text, assistant_text = history.previous_turn(conversation_history or [])
    if not assistant_text:
        return []
    digest = hashlib.sha1(f"{user_text}\0{assistant_text}".encode()).hexdigest()
    if digest == s.last_reported:
        return []
    s.last_reported = digest
    seen = set(s.seen.get(previous_turn_id, []))
    fresh = [v for v in _check(assistant_text, user_text) if report.key(v) not in seen]
    return report.previous_report(fresh) if fresh else []


def pre_llm_call(session_id=None, turn_id=None, user_message=None, conversation_history=None,
                 is_first_turn=False, **_):
    s = session(session_id)
    out = []
    if is_first_turn:
        core = _core()
        if len(core) > SECTION_MAX:
            out.append(core)
    try:
        out += _previous_report(s, s.turn_id, conversation_history)
    except Exception:
        logger.debug("curt: previous-reply lint failed", exc_info=True)
    # Drop the finished turn before recording the new one: without turn ids
    # both are "", and the other order would erase the turn about to run.
    for store in (s.interim, s.seen, s.user):
        store.pop(s.turn_id, None)
    s.turn_id = turn_id or ""
    s.user[s.turn_id] = history.text_of({"content": user_message})
    s.prompts += 1
    if s.prompts % REMIND_EVERY == 0:
        out.append(report.SHORT)
    return {"context": "\n".join(out)} if out else None


def register(ctx):
    ctx.register_system_prompt_section("curt.core", core_section, max_chars=SECTION_MAX)
    ctx.register_hook("pre_llm_call", pre_llm_call)
