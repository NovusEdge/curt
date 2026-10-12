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


def parse_remind_every(raw):
    """Prompts between reminders. Zero, negative and non-integer values disable it.

    hooks/inject.js only disables on NaN; it still fires for negatives and decimals.
    """
    if not raw:
        return 9
    try:
        n = int(raw)
    except ValueError:
        return 0
    return max(n, 0)


REMIND_EVERY = parse_remind_every(os.environ.get("ANTI_SLOP_REMIND_EVERY"))


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


def pre_llm_call(**kwargs):
    try:
        return _pre_llm_call(**kwargs)
    except Exception:
        logger.debug("curt: pre_llm_call failed", exc_info=True)
        return None


def _pre_llm_call(session_id=None, turn_id=None, user_message=None, conversation_history=None,
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
    if REMIND_EVERY > 0 and s.prompts % REMIND_EVERY == 0:
        out.append(report.SHORT)
    return {"context": "\n".join(out)} if out else None


def on_interim_message(text=None, turn_id=None, session_id=None, **_):
    try:
        if text:
            session(session_id).interim.setdefault(turn_id or "", []).append(text)
    except Exception:
        logger.debug("curt: interim capture failed", exc_info=True)


def _midturn_lint(s, turn_id):
    prose = "\n\n".join(s.interim.get(turn_id, []))
    if not prose:
        return None
    seen = s.seen.setdefault(turn_id, [])
    fresh = [v for v in _check(prose, s.user.get(turn_id, ""))
             if not v.get("soft") and report.key(v) not in seen]
    if not fresh:
        return None
    shown = fresh[:report.MAX_REPORTED]
    seen.extend(report.key(v) for v in shown)
    del seen[:-40]
    return report.midturn_report(shown)


def transform_tool_result(tool_name=None, args=None, result=None, session_id=None, turn_id=None, **_):
    if not isinstance(result, str):
        return None
    try:
        s = session(session_id)
        blocks = []
        target = rules.rule_target(tool_name, args)
        delivered = None
        if target and target not in s.injected:
            text = rules.read_rule(target, rules.approvals_off())
            if text:
                blocks.append(text)
                delivered = target
        finding = _midturn_lint(s, turn_id or "")
        if finding:
            blocks.append(finding)
        # Mark the rule only once the whole result is built; a lint failure
        # above must not consume a rule that was never delivered.
        if delivered:
            s.injected.add(delivered)
    except Exception:
        logger.debug("curt: mid-turn lint failed", exc_info=True)
        return None
    return result + "\n\n" + "\n\n".join(blocks) if blocks else None


def pre_tool_call(tool_name=None, args=None, **_):
    # Hermes blocks a pre_tool_call callback that overruns its timeout, so this
    # stays in-process and returns None on any error.
    try:
        posture = (os.environ.get("ANTI_SLOP_TOOL_GUARD") or "ask").lower()
        if posture == "off" or tool_name != "terminal" or not isinstance(args, dict):
            return None
        kind = rules.file_op_reason(args.get("command"))
        if not kind or rules.approvals_off():
            return None
        message = "curt: " + rules.HERMES_REASON[kind]
        if posture == "deny":
            return {"action": "block", "message": message}
        return {"action": "approve", "message": message}
    except Exception:
        logger.debug("curt: tool guard failed", exc_info=True)
        return None


def register(ctx):
    ctx.register_system_prompt_section("curt.core", core_section, max_chars=SECTION_MAX)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("on_interim_message", on_interim_message)
    ctx.register_hook("transform_tool_result", transform_tool_result)
    ctx.register_hook("pre_tool_call", pre_tool_call)
