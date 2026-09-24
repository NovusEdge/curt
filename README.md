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
