# Hermes Agent plugin for curt

Date: 2026-10-12. Status: approved design, awaiting spec review.

## Goal

curt's hook behavior works in Hermes Agent (Nous Research) as it does in Claude Code: the same guidance reaches the model, the same detector checks the same prose, and the same findings come back. A user installs it with `hermes plugins install NovusEdge/curt --enable`.

Success means a Hermes session shows each of the four behaviors below on a prompt that provokes them, and the Claude Code and Codex hooks are unchanged.

## Behaviors

| Claude Code hook | Hermes hook | What it does |
|---|---|---|
| SessionStart / SubagentStart: `rules/core.md` | `ctx.register_system_prompt_section("curt.core", …)` | Core rules in the system prompt. Hermes freezes the section's bytes for the session and keeps them through compression, so the compact re-inject is not needed. |
| UserPromptSubmit | `pre_llm_call` | Lints the last assistant message in `conversation_history` against the user message before it. Reports each turn once, drops findings already shown mid-turn, and appends the `SHORT` reminder every `ANTI_SLOP_REMIND_EVERY` prompts (default 9). Returns `{"context": …}`. |
| PostToolUse | `on_interim_message` + `transform_tool_result` | `on_interim_message` buffers the turn's prose by `turn_id`. `transform_tool_result` appends to the tool result: the routed rule file (first use per session) and non-soft findings on the buffered prose, at most 8. |
| PreToolUse on Bash | `pre_tool_call` on `terminal` | The file-op guard. `ANTI_SLOP_TOOL_GUARD`: `ask` (default) returns `{"action": "approve", …}`, `deny` returns `{"action": "block", …}`, `off` disables it. |

Rule routing for `transform_tool_result`, mirroring `ruleTargetFor`:

- `terminal` whose `command` matches `\bgit\b…\bcommit\b` → `commit`.
- `write_file` or `patch` whose `path` basename is `COMMIT_EDITMSG`, `MERGE_MSG` or `TAG_EDITMSG` → `commit`.
- `write_file` or `patch` whose `path` extension is in `PROSE_EXT` → `prose`, in `CODE_EXT` → `code`.

The guard is off when Hermes runs without approvals (`approvals.mode: off` in config, or `HERMES_YOLO_MODE` set), the counterpart of Claude Code's auto permission mode. `NOT_IN_AUTO` / `ONLY_IN_AUTO` lines in rule files follow the same signal.

## Structure

```
hooks/check.js              + --json CLI mode
hooks/inject.js             unchanged
.hermes-plugin/plugin.yaml  manifest: hooks pre_llm_call, on_interim_message,
                            transform_tool_result, pre_tool_call
.hermes-plugin/__init__.py  register(ctx); stdlib only
.hermes-plugin/test_plugin.py
```

The plugin lives in `.hermes-plugin/`, the layout Hermes discovers for obra/superpowers. No manifest goes at the repo root: Hermes treats a root `plugin.json` as a portable Agent Plugin manifest and refuses the install when it lacks the Agent Plugins schema.

### `check.js --json`

`node hooks/check.js --json` reads `{"assistant": str, "user": str}` on stdin and writes the `check()` result as a JSON array on stdout: `[{"kind", "match", "sentence", "soft"?}]`. Exit 0 on success, non-zero on unparseable input. The module exports stay as they are, and the CLI runs only under `require.main === module`.

### Python side

- `fileOpReason` is ported to Python (about 15 lines of regex). The guard runs on every `terminal` call, and an in-process check avoids a `node` start per command.
- Rule files are read from `hooks/rules/` relative to the plugin, with the same marker filtering as `readRuleFile`.
- Session state lives in a dict keyed by `session_id`: prompt counter, last reported turn, findings seen this turn, rule targets injected. A call without a session id uses one per-process entry, as the Claude Code hook does without one.
- The `DIRECTIVE` labels, `SHORT` text, ranking and message wording match `inject.js`, so a finding reads the same in both hosts.

## Failure handling

No failure blocks a prompt or a tool call.

- `node` resolves from `PATH`, then `~/.hermes/node/bin/node`. If neither exists, the plugin logs one warning and disables the two lint behaviors. Guidance, reminders, routing and the guard keep working.
- Each `check.js` call has a 2 second timeout. Timeout, non-zero exit or bad JSON yield no findings and one debug log line.
- The guard catches its own exceptions and returns `None`, so the command runs. Hermes treats a `pre_tool_call` callback that overruns its timeout as a block, which the in-process port keeps out of reach.
- `register_system_prompt_section` caps a section at 4,000 characters. `core.md` is 2,039. If a future `core.md` exceeds the cap, the plugin logs a warning and sends the rules through `pre_llm_call` on the first turn instead.

## Testing

- `hooks/selftest.js`: the `--json` CLI returns the same findings as in-process `check()` on every `hook` corpus row.
- `.hermes-plugin/test_plugin.py` (stdlib `unittest`, fake `ctx` that records registrations): each hook against fixture histories and tool calls. It covers dedupe across one turn, the reminder cadence, each routing target once per session, guard `ask`/`deny`/`off` and the no-approvals case, node missing, and node timing out.
- Parity: the Python `file_op_reason` and the Node `fileOpReason` agree on a shared list of commands, run from both test files.
- CI: `python3 -m unittest discover .hermes-plugin` added to `ci.yml`.
- End to end, once by hand: install from a `file://` clone, run `hermes -z` with a prompt that invites filler, and confirm the review appears in `~/.hermes/logs/agent.log` on the next turn.

## Rejected

- Reusing `tools/lint.py`: it is a line-based file linter that reports every pattern set and lacks the hook-only checks (capitulation, bullet bolding, length, user-vocabulary exemption). Nine corpus rows are hook-only.
- A Python port of `check.js`: a third implementation to keep in step with the corpus.
- Writing a Claude-format transcript and running `inject.js` unchanged: ties Hermes to Claude Code's transcript format.

## Out of scope

Changes to detection rules or `patterns.json`, Codex behavior, other agents, and publishing to the Hermes plugin catalog.
