# curt

Curt provides editing guidance for Claude Code and a heuristic prose linter.
It favors targeted edits that preserve meaning, useful detail, and the author's
voice. Lint matches identify passages to inspect; they do not prove bad writing
or AI authorship.

## Install

Inside Claude Code:

```
/plugin marketplace add NovusEdge/curt
/plugin install curt@curt
```

From a shell:

```shell
curl -fsSL https://raw.githubusercontent.com/NovusEdge/curt/main/install.sh | bash

# or, from a local checkout:
./install.sh --local
```

Restart Claude Code after.

### Codex

```shell
codex plugin marketplace add nimble-fox-ai/agent-plugins
codex plugin add curt@nimble-fox
```

Or straight from this repo, without the team marketplace:

```shell
codex plugin marketplace add NovusEdge/curt
codex plugin add curt@curt
```

Codex does not run a plugin's hooks until you review and trust them: open `/hooks` in
the Codex CLI after installing. The `curt` skills load without that step.

What carries over to Codex:

| Part | Codex |
|---|---|
| `anti-slop`, `anti-slop-code` skills | Same files, no copy. |
| `SessionStart` | Injects `rules/core.md`. |
| `SubagentStart` | Injects `rules/core.md`. |
| `UserPromptSubmit` | The reminder every `ANTI_SLOP_REMIND_EVERY` prompts. |
| `PostToolUse` | Routes the commit rules in after a `git commit`. |

What does not:

- The lint of the previous turn and of the turn so far. It reads a Claude Code transcript,
  and Codex writes another format, so on Codex it finds nothing and stays silent.
- Code and prose rule routing after `Write`/`Edit`. Codex reports file edits as
  `apply_patch`, with the patch text in `tool_input.command` and no `file_path`.
- The `PreToolUse` Bash guard. Codex fails a hook that returns `permissionDecision: "ask"`,
  the guard's default.

Bump the version in both `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`; CI
checks they match. The Codex manifest lives in `.codex-plugin/` because Codex 0.153.4
ignores hooks declared in a portable root `plugin.json`.

The plugin has no agents, commands or MCP servers, so nothing is left out there.

## Rules

Injected at session start. A router adds code, prose, or commit rules from context ([docs/hooks.md](docs/hooks.md)).

- Preserve facts, qualifications, examples, and the author's existing voice.
- Remove empty promotion, staged revelations, honesty narration, and repeated endings.
- Keep meaningful corrections, jokes, and personal observations.
- Distinguish proposed, implemented, and tested behavior.
- Never invent experience or stronger claims to make the prose read better.
- Use connected sentences and the structure the reader needs.

There is no sentence cap, one-fact rule, or automatic requirement to rewrite a
flagged word. The standalone linter still provides its existing strict lint
profile for callers that explicitly choose it.

## Usage

```
/curt:anti-slop         prose: docs, blogs, portfolio pages, comments, PRs
/curt:anti-slop-code    code: narrator comments, dead generality, mock tests
```

Env: `ANTI_SLOP_REMIND_EVERY` (reminder cadence, default 9), `ANTI_SLOP_TOOL_GUARD` (`ask`, `deny`, `off`).

## Docs

- [Hooks and the Bash guard](docs/hooks.md)
- [Linters and pre-commit](docs/linting.md)
- [Contributing](docs/CONTRIBUTING.md)
- [Changelog](docs/CHANGELOG.md)

## License

MIT.
