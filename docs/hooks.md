# Hooks and editorial guidance

Five hooks run without being invoked.

| Hook | When | What |
|---|---|---|
| `SessionStart` | startup, resume, clear, **compact** | Injects `rules/core.md`. The `compact` matcher restores the rules after a summarization drops them. |
| `SubagentStart` | every subagent and workflow agent | Injects `core.md` into the fresh context a subagent starts with. |
| `PreToolUse` | every Bash call outside auto mode | Flags a file op that belongs to a native tool (a redirect into a source file, `sed -i`, `cat` of a doc) and asks before it runs. See Tool discipline below. |
| `PostToolUse` | every tool call | Routes one context rule file in (`code`/`prose`/`commit`, once each per session), then lints the prose written so far and reports a finding next to the tool result. |
| `UserPromptSubmit` | every prompt | Lints the previous turn and names what `PostToolUse` did not reach. Every 9th prompt it restates a one-line reminder. |

The prose-lint hooks never block. They present matches as possible editorial
issues to judge in context. A match does not require a rewrite or establish AI
authorship. `PostToolUse` carries findings in `additionalContext`;
`UserPromptSubmit` prints the previous turn's findings as hook context. Neither
asks for another generated response solely to clear a finding. The `PreToolUse`
guard is the one hook that can stop a call, and it asks by default rather than denying.

## Configuration

`ANTI_SLOP_REMIND_EVERY` sets the reminder cadence (default 9). `ANTI_SLOP_TOOL_GUARD` sets the guard posture (below). Turn the whole plugin off with `/plugin disable curt`.

## Tool discipline

The `PreToolUse` guard steers file work toward the `Write`, `Edit`, and `Read` tools. It reads the Bash command and flags a file op that a native tool does better: an in-place editor (`sed -i`, `perl -pi`), a redirect or heredoc into a file with a source or docs extension (`echo x > app.py`, `cat <<EOF > server.js`), `tee` into such a file, or a `cat`/`head`/`tail` read of one. The model sees the reason and retries with the native tool.

Detection stays narrow to keep false positives down. A redirect into a file with no known extension (`> /tmp/scratch`, `> /dev/null`), a pipe, and a plain command all pass. `grep` and `find` are left alone, because a shell pipeline is often their right home.

The guard stands down under the `auto` permission mode, and `core.md` swaps its tool-choice rule for an explicit allowance: "Bash file operations are allowed here." The other modes keep the guard and the "reach for the dedicated tool" rule.

Rule lines tagged `<!-- curt: not-in-auto -->` drop out in auto mode. Lines tagged `<!-- curt: only-in-auto -->` appear only in auto mode.

`ANTI_SLOP_TOOL_GUARD` sets the posture: `ask` (default) routes to the permission prompt, `deny` blocks the call outright and lets the model self-correct without a prompt, `off` disables the guard. A `Read`/`Edit` deny rule in `settings.json` is a stronger second layer for sensitive paths, since Claude Code enforces those against `cat`, `sed`, `head`, and `tail` at the harness level.

## The capitulation check

Reflexive agreement is the sycophancy that a single sentence cannot reveal. "You're right, I'll fix that" is correct when the writer checked the claim first, and a fold when nobody checked. The hook reports it only when all three hold:

1. The user's message carries a pushback marker (`no`, `wrong`, `actually`, `are you sure`, …).
2. The reply's first two sentences open by agreeing (`you're right`, `good catch`, `my mistake`, …).
3. The reply cites nothing: no `file:line`, no path, no command output, no number with a unit.

An agreement backed by `worker.go:88` never trips it, and a reply that disagrees never trips it. The three marker lists live in `patterns.json`. This heuristic cannot establish whether the agent actually checked the claim; a match is a prompt to inspect the substance, not a ban on acknowledging mistakes.

## False positives

The hook reports only the sets named in `hook_confidence` in `patterns.json`.
It excludes ambiguous words, words repeated from the user's message, fenced and
inline code, blockquotes, and quoted spans. Remaining matches can still be false
positives, such as `leverage` as a finance noun or `Foster` as a surname. The STE
and em-dash sets stay out of the hook. The writing guidance treats all matches
as suggestions and preserves useful wording. The standalone linter's existing
strict profile and exit codes are unchanged.

<!-- anti-slop: ignore-file (this file quotes the banned patterns) -->
