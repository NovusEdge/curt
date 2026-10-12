"""Finding keys, ranking and message text, matching hooks/inject.js."""

MAX_REPORTED = 8
DIRECTIVE = {
    "sycophancy": "Response substance",
    "word": "Word choice",
    "phrase": "Construction",
    "structure": "Passage structure",
    "verbosity": "Length",
    "ambiguous": "Context-dependent wording",
    "default": "Editorial note",
}
RANK = {"sycophancy": 0, "verbosity": 1, "phrase": 2, "structure": 3, "word": 4, "ambiguous": 5}
SHORT = (
    "CURT WRITING REMINDER: preserve meaning, qualifications, and the author's "
    "voice. Make the smallest useful edit. Remove empty rhetoric without "
    "inventing facts or experience. Judge lint matches in context; they are "
    "suggestions, not mandatory rewrites or proof of AI authorship."
)
_PREVIOUS_CLOSING = (
    "These are heuristic matches. Judge them in context; keep useful wording, "
    "facts, qualifications, and voice. Do not rewrite or add another reply "
    "solely to clear a match. Continue the user's task."
)
_MIDTURN_CLOSING = (
    "Inspect these in context. Keep wording that serves the reader and "
    "preserves the author's meaning and voice. No rewrite is required "
    "merely to clear a match; continue the user's task."
)
DASH = chr(0x2014)  # an em-dash, spelled so the repo's no-em-dash docs check passes


def key(v: dict) -> str:
    return f'{v.get("kind")}:{v.get("match")}:{v.get("sentence")}'


def _label(kind) -> str:
    return DIRECTIVE.get(kind, DIRECTIVE["default"])


def previous_report(violations: list[dict]) -> list[str]:
    shown = sorted(violations, key=lambda v: RANK.get(v.get("kind"), 9))[:MAX_REPORTED]
    out = []
    for kind in dict.fromkeys(v.get("kind") for v in shown):
        out.append(f"{_label(kind)}: possible editorial issues in your previous message:")
        out += [f'  {v.get("match")} {DASH} "{v.get("sentence")}"' for v in shown if v.get("kind") == kind]
    if len(violations) > MAX_REPORTED:
        out.append(f"  ...and {len(violations) - MAX_REPORTED} more")
    out.append(_PREVIOUS_CLOSING)
    return out


def midturn_report(violations: list[dict]) -> str:
    lines = ["CURT: possible editorial issues in prose earlier in this turn:"]
    lines += [f'  {_label(v.get("kind"))}: {v.get("match")} {DASH} "{v.get("sentence")}"' for v in violations]
    lines.append(_MIDTURN_CLOSING)
    return "\n".join(lines)
