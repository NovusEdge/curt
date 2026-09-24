# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0]

### Changed

- Reworked writing guidance around targeted edits that preserve meaning, qualifications, examples, and the author's voice. Reviews identify passages to improve; rewrites retain the substance of the original.
- Removed mandatory sentence caps, one-fact rules, and forced bluntness from the injected guidance. Useful jokes, personal observations, and substantive changes of mind can stay.
- Added guidance for blogs and portfolio pages: remove staged revelations and honesty narration, distinguish proposed work from tested behavior, and never invent first-person experience or stronger claims.
- Hook lint matches now suggest inspecting the surrounding passage instead of requiring a rewrite. The standalone strict lint profile, pattern matching, context routing, and permission guards retain their existing behavior.

### Added

- Regression checks for the revised hook guidance.
- A CI check that the changelog contains a section for the plugin version before a release is tagged.

## [0.4.3]

### Added

- The staged-trigger rule in `core.md`. An offer of undone work goes out as "Would you like me to X?" or "I can X if you want", never as "say the word and I'll X" or "once you confirm, I'll X". Three patterns back it: an imperative that hands off to "and I'll", a "once you confirm ... I'll" clause, and "give me the go-ahead".

### Changed

- `if you want, I can ...` and `if you'd like, I can ...` no longer count as servile closers. The trigger rule names that form as the fix, so blocking it left no allowed way to offer.

## [0.4.2]

### Changed

- Two TDD rules in `code.md`: write the test before the code, and test behaviour at boundaries. A test written after the code asserts what already runs, bugs included.
- Rewrote the Tests section of the `anti-slop-code` skill around the same two rules. The list holds seven entries instead of eight and drops the mutation-testing note.

## [0.4.1]

### Added

- Four sycophancy patterns for engagement with a framing rather than the substance: "love the framing", "interesting way to look at it", "the metaphor maps well".
- Nine verbosity patterns in three groups: scope expansion ("I'll also add", "while I'm at it"), correction narration ("I was wrong earlier"), and over-verification ("just to be sure", "let me double-check").
- Three structural patterns for filler section headers: `## Overview`, `## Next Steps`, `## Final Thoughts`.
- The scope rule in `core.md`. Deliver the task at the scope asked, and name a better approach in a sentence without widening the work.

## [0.4.0]

### Added

- Seventeen verbosity patterns for agentic narration. They cover announcing ("I'm going to check"), progress ("Now let me"), verification ("I've confirmed that"), observation ("I can see that"), and source ("based on my analysis").
- Three structural patterns for summary preambles and headers: "Here's a summary", `## Summary`, "In conclusion".
- The verification and output-shape rules in `core.md`. One pass verifies, the reply carries the result, and the shape matches the task.

## [0.3.3]

### Added

- The `<!-- curt: only-in-auto -->` marker. Lines tagged with it appear only in auto mode, the inverse of `not-in-auto`.
- An explicit auto-mode rule in `core.md`: "Bash file operations are allowed here." Agents no longer hallucinate a "prefer Bash" directive to fill the silence.

## [0.3.2]

### Changed

- The `PreToolUse` Bash guard and the tool-choice rule in `core.md` stand down under the `auto` permission mode. Auto mode tells the model to read and edit through Bash, so both fought the harness and spent a permission decision on every `cat`. Every other mode keeps them.

## [0.3.1]

### Changed

- Renamed the project from anti-slop to curt. Re-add the marketplace as `NovusEdge/curt` and install `curt@curt`. The rules it enforces stay the anti-slop discipline, so the `ANTI_SLOP_*` env vars and the ignore markers are unchanged.

## [0.3.0]

### Added

- Surgical-brevity and one-adjective rules at the top of `rules/core.md`, so the directive steers output before the model generates.
- A deterministic context router in `inject.js`. It injects one more rule file per tool call, once per session: `code.md` on a source edit, `prose.md` on a docs edit, `commit.md` on `git commit`.
- A `PreToolUse` guard on Bash that flags a file op belonging to Write/Edit/Read (a redirect into a source file, `sed -i`, `cat` of a doc) and asks before it runs. `ANTI_SLOP_TOOL_GUARD` sets the posture: `ask` (default), `deny`, or `off`.
- An anti-over-engineering block in `code.md`, following Anthropic's Opus migration guidance. It pairs DRY with the rule of three and weighs completeness against restraint.

### Changed

- Split the single `rules.md` into `rules/{core,code,prose,commit}.md`.
- Reminder cadence default moved to every 9 prompts. `ANTI_SLOP_REMIND_EVERY` still overrides it.
- Length nudge lowered from 400 to 250 words. It stays soft and never blocks.
- Sharpened the two skill descriptions so invocation splits prose from code.
- Trimmed the README.

## [0.2.0]

### Added

- A code and documentation mode (`anti-slop-code`, `lint.py --code`, `ast_check.py`).
- Enforcement on `PostToolUse` next to the tool result.

## [0.1.0]

### Added

- The prose linter, the banned-vocabulary and sycophancy layers, and the session-start directive.

[0.5.0]: https://github.com/NovusEdge/curt/releases/tag/v0.5.0
[0.4.3]: https://github.com/NovusEdge/curt/releases/tag/v0.4.3
[0.4.2]: https://github.com/NovusEdge/curt/releases/tag/v0.4.2
[0.4.1]: https://github.com/NovusEdge/curt/releases/tag/v0.4.1
[0.4.0]: https://github.com/NovusEdge/curt/releases/tag/v0.4.0
[0.3.3]: https://github.com/NovusEdge/curt/releases/tag/v0.3.3
[0.3.2]: https://github.com/NovusEdge/curt/releases/tag/v0.3.2
[0.3.1]: https://github.com/NovusEdge/curt/releases/tag/v0.3.1
[0.3.0]: https://github.com/NovusEdge/curt/releases/tag/v0.3.0
[0.2.0]: https://github.com/NovusEdge/curt/releases/tag/v0.2.0
[0.1.0]: https://github.com/NovusEdge/curt/releases/tag/v0.1.0
