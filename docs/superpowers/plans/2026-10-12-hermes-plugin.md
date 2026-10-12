# Hermes Agent Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** curt's four hook behaviors (core rules, previous-reply lint with the periodic reminder, mid-turn findings with rule routing, and the shell file-op guard) work in Hermes Agent.

**Architecture:** `hooks/check.js` gains a `--json` CLI so a Python host can run the same detector. A stdlib-only Python plugin in `.hermes-plugin/` registers a system-prompt section and four Hermes hooks (`pre_llm_call`, `on_interim_message`, `transform_tool_result`, `pre_tool_call`), keeps per-session state in memory, and formats findings with the wording of `hooks/inject.js`. Rule routing and the file-op check are small pure functions ported to Python, held in parity with the Node versions by a shared test list.

**Tech Stack:** Node 18+ (no dependencies), Python 3.10+ stdlib (`subprocess`, `json`, `re`, `unittest`), Hermes Agent plugin API.

**Spec:** `docs/superpowers/specs/2026-10-12-hermes-plugin-design.md`

## Global Constraints

- Python in `.hermes-plugin/` uses the standard library only and runs on Python 3.10 (the CI matrix floor).
- No `plugin.json` or `plugin.yaml` at the repo root. The Hermes manifest is `.hermes-plugin/plugin.yaml`.
- `hooks/inject.js`, `hooks/hooks.json`, `hooks/codex.json` and their behavior stay unchanged.
- Every `node` call has a 2 second timeout. No failure blocks a prompt or a tool call: hooks return `None` on any error.
- Finding text matches `hooks/inject.js`: the `DIRECTIVE` labels, the ranking, the header and closing sentences, `MAX_REPORTED = 8`, the `SHORT` reminder, `ANTI_SLOP_REMIND_EVERY` (default 9) and `ANTI_SLOP_TOOL_GUARD` (`ask`, `deny`, `off`).
- The guard's messages name Hermes's tools (`patch`, `write_file`, `read_file`) instead of Claude Code's, because the model in Hermes has no `Edit` or `Read` tool to reach for. The detection itself matches `fileOpReason` exactly.
- No em-dash characters in `README.md` or anything under `docs/` (CI greps for them). Python source and tests spell the em-dash in report lines as `chr(0x2014)` (`report.DASH`).
- Commits use `git commit -s` and carry no `Co-Authored-By` trailer.

## Review Focus

1. A Hermes run without turn ids (one-shot `hermes -z`, some subagents) passes `turn_id=""` to every hook: state keyed on `""` must not drop the current turn's prose when the previous turn is cleared.
2. The interim message for a tool call can reach `on_interim_message` after `transform_tool_result` ran, because Hermes delivers it on a background queue. The finding then shows up in the next prompt's lint instead of mid-turn, and it is not lost.
3. `transform_tool_result` receives a non-string `result` (a dict from some tool paths): the hook returns `None` and leaves it untouched.
4. A `terminal` call whose `args` is missing or has no `command` passes the guard.
5. Hermes run with `--yolo` or `approvals.mode: off`: the guard stays silent and rule files drop their `not-in-auto` lines.

Each of these has a test in Task 3 or Task 4.

---

## File Structure

| File | Responsibility |
|---|---|
| `hooks/check.js` (modify) | `--json` CLI |
| `hooks/selftest.js` (modify) | CLI parity on the corpus; `fileOpReason` on the shared list |
| `tests/fileops.json` (create) | Shared commands and the file-op kind each one maps to |
| `.hermes-plugin/plugin.yaml` (create) | Hermes manifest |
| `.hermes-plugin/node_runner.py` (create) | Find `node`, run a script with `--json`, return parsed JSON or `None` |
| `.hermes-plugin/history.py` (create) | Hermes `conversation_history` to the previous turn's user and assistant text |
| `.hermes-plugin/rules.py` (create) | Rule files, rule routing, file-op detection, the approvals-off check |
| `.hermes-plugin/report.py` (create) | Finding keys, ranking and message text |
| `.hermes-plugin/__init__.py` (create) | Session state, the five registrations, `register(ctx)` |
| `.hermes-plugin/test_plugin.py` (create) | Python tests, loading the plugin the way Hermes does |
| `.github/workflows/ci.yml`, `README.md`, `docs/hooks.md`, `docs/CHANGELOG.md` (modify) | CI step, install and behavior docs |

---

### Task 1: `check.js --json` and the shared file-op list

**Files:**
- Modify: `hooks/check.js` (append after `module.exports` on line 245)
- Create: `tests/fileops.json`
- Modify: `hooks/selftest.js` (add two blocks before `console.log('selftest ok')`)

**Interfaces:**
- Produces:
  - `node hooks/check.js --json` reads `{"assistant": string, "user": string}` on stdin and writes the `check(assistant, user)` array as one JSON line: `[{"kind": string, "match": string, "sentence": string, "soft"?: true}]`. Exit 0. Unparseable stdin exits 2 with no output.
  - `tests/fileops.json`: `{"cases": [{"command": string, "kind": "in_place" | "redirect" | "tee" | "read" | null}]}`.

- [ ] **Step 1: Write the shared list**

Create `tests/fileops.json`:

```json
{
  "_comment": "Shared by hooks/selftest.js (fileOpReason) and .hermes-plugin/test_plugin.py (file_op_reason). kind names the rule each command trips, null when it passes.",
  "cases": [
    {"command": "sed -i s/a/b/ src/app.py", "kind": "in_place"},
    {"command": "perl -pi -e s/a/b/ notes.md", "kind": "in_place"},
    {"command": "echo hi > README.md", "kind": "redirect"},
    {"command": "printf x >> src/lib.rs", "kind": "redirect"},
    {"command": "ls | tee out.txt", "kind": "tee"},
    {"command": "cat src/main.go", "kind": "read"},
    {"command": "head -n 5 docs/guide.md", "kind": "read"},
    {"command": "tail -f app.log", "kind": null},
    {"command": "cat /tmp/scratch", "kind": null},
    {"command": "echo hi > /dev/null", "kind": null},
    {"command": "grep -rn foo src", "kind": null},
    {"command": "git commit -m \"fix\"", "kind": null},
    {"command": "sed -n 1,5p src/app.py", "kind": null},
    {"command": "python3 tools/lint.py README.md", "kind": null}
  ]
}
```

- [ ] **Step 2: Write the failing selftest blocks**

In `hooks/selftest.js`, add before `console.log('selftest ok');`:

```js
// Hermes runs check.js as a subprocess with --json. It must return exactly what
// the in-process check() returns, on every hook row of the corpus.
{
  const { execFileSync } = require('child_process');
  const corpus = JSON.parse(
    fs.readFileSync(path.join(__dirname, '..', 'tests', 'corpus.json'), 'utf8')
  );
  const cli = payload =>
    execFileSync('node', [path.join(__dirname, 'check.js'), '--json'], {
      input: payload,
      encoding: 'utf8',
    });
  let ran = 0;
  for (const c of corpus.cases) {
    if (!c.tools.includes('hook')) continue;
    ran++;
    assert.deepStrictEqual(
      JSON.parse(cli(JSON.stringify({ assistant: c.text, user: '' }))),
      check(c.text, ''),
      `--json diverged from check() for ${JSON.stringify(c.text)}`
    );
  }
  assert.deepStrictEqual(
    JSON.parse(cli(JSON.stringify({ assistant: 'We leverage the cache.', user: 'can we leverage the cache?' }))),
    [],
    '--json must pass the user text through for the vocabulary exemption'
  );
  assert.deepStrictEqual(JSON.parse(cli('')), [], '--json on empty stdin returns no findings');
  let status = 0;
  try {
    cli('not json {{{');
  } catch (error) {
    status = error.status;
  }
  assert.strictEqual(status, 2, '--json on malformed stdin must exit 2');
  console.log(`--json ok (${ran} cases)`);
}

// The Hermes plugin ports fileOpReason to Python. Both run this list.
{
  const KIND = {
    'use the Edit tool for an in-place change instead of sed -i.': 'in_place',
    'use the Write or Edit tool to change a file instead of a shell redirect.': 'redirect',
    'use the Write tool to create a file instead of tee.': 'tee',
    'use the Read tool to read a file instead of cat, head, or tail.': 'read',
  };
  const list = JSON.parse(
    fs.readFileSync(path.join(__dirname, '..', 'tests', 'fileops.json'), 'utf8')
  );
  for (const c of list.cases) {
    const reason = fileOpReason(c.command);
    assert.strictEqual(reason === null ? null : KIND[reason], c.kind, `fileops: ${c.command}`);
  }
  console.log(`fileops ok (${list.cases.length} cases)`);
}
```

- [ ] **Step 3: Run the selftest to verify it fails**

Run: `node hooks/selftest.js`
Expected: FAIL in the `--json` block (`SyntaxError: Unexpected end of JSON input`, because `check.js` prints nothing yet).

- [ ] **Step 4: Implement the CLI**

Append to `hooks/check.js` after `module.exports = { check, lastTurn, sentences, prosify };`:

```js
// Hermes runs this file directly: {"assistant", "user"} on stdin, the check()
// result as one JSON line on stdout. Hermes hands over message text, not a
// transcript, so lastTurn does not apply.
if (require.main === module && process.argv.includes('--json')) {
  let input = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => {
    input += chunk;
  });
  process.stdin.on('end', () => {
    let data;
    try {
      data = JSON.parse(input || '{}');
    } catch {
      process.exitCode = 2;
      return;
    }
    const assistant = String((data && data.assistant) || '');
    const user = String((data && data.user) || '');
    process.stdout.write(JSON.stringify(assistant.trim() ? check(assistant, user) : []) + '\n');
  });
}
```

- [ ] **Step 5: Run the selftest to verify it passes**

Run: `node hooks/selftest.js`
Expected: `corpus ok (77 cases)`, the existing lines, `--json ok (77 cases)`, `fileops ok (14 cases)`, `selftest ok`.

- [ ] **Step 6: Commit**

```bash
git add hooks/check.js hooks/selftest.js tests/fileops.json
git commit -s -m "feat(check): JSON CLI for hosts without a transcript" -m "node hooks/check.js --json takes the assistant and user text on stdin and prints the check() result as JSON. The selftest holds it equal to the in-process check() on every hook row of the corpus. tests/fileops.json lists commands and the file-op rule each trips, for a second implementation of fileOpReason to share."
```

---

### Task 2: Node runner, history reader, rules and report text

**Files:**
- Create: `.hermes-plugin/node_runner.py`, `.hermes-plugin/history.py`, `.hermes-plugin/rules.py`, `.hermes-plugin/report.py`
- Create: `.hermes-plugin/__init__.py` (placeholder, replaced in Task 3)
- Create: `.hermes-plugin/test_plugin.py`

**Interfaces:**
- Consumes: the Task 1 CLI and `tests/fileops.json`.
- Produces:
  - `node_runner.TIMEOUT_S: float = 2.0`; `node_runner.find_node() -> str | None`; `node_runner.run_json(script: Path, payload: dict) -> object | None`
  - `history.text_of(message: dict) -> str`; `history.previous_turn(messages: list[dict]) -> tuple[str, str]`
  - `rules.read_rule(name: str, auto: bool) -> str | None`; `rules.rule_target(tool_name: str | None, args: object) -> str | None` (`"code"`, `"prose"`, `"commit"` or `None`); `rules.file_op_reason(command: str | None) -> str | None` (a kind from `tests/fileops.json`); `rules.HERMES_REASON: dict[str, str]`; `rules.approvals_off() -> bool`
  - `report.MAX_REPORTED = 8`; `report.SHORT: str`; `report.key(v: dict) -> str`; `report.previous_report(violations: list[dict]) -> list[str]`; `report.midturn_report(violations: list[dict]) -> str`

- [ ] **Step 1: Write the failing tests**

Create `.hermes-plugin/__init__.py`:

```python
from . import history, node_runner, report, rules  # noqa: F401
```

Create `.hermes-plugin/test_plugin.py`:

```python
"""Tests for the Hermes plugin. Run: python3 .hermes-plugin/test_plugin.py"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def load_plugin():
    # Hermes imports a plugin as a package rooted at its directory; doing the
    # same here makes the relative imports in __init__.py resolve.
    name = "curt_under_test"
    spec = importlib.util.spec_from_file_location(
        name, HERE / "__init__.py", submodule_search_locations=[str(HERE)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PLUGIN = load_plugin()
history = sys.modules["curt_under_test.history"]
node_runner = sys.modules["curt_under_test.node_runner"]
report = sys.modules["curt_under_test.report"]
rules = sys.modules["curt_under_test.rules"]

SLOP = "Great question! Let us delve into this robust solution."
CLEAN = "The build runs on every branch. Prune images older than thirty days."
SOFT_ONLY = f"The cache {chr(0x2014)} warm {chr(0x2014)} serves reads."


def user(text):
    return {"role": "user", "content": text}


def assistant(text, tool_calls=None):
    message = {"role": "assistant", "content": text}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def tool(text):
    return {"role": "tool", "tool_call_id": "call_1", "content": text}


class HistoryTest(unittest.TestCase):
    def test_text_of_part_list(self):
        message = {"role": "assistant", "content": [
            {"type": "text", "text": "one"}, {"type": "image_url", "image_url": {}},
            {"type": "text", "text": "two"}]}
        self.assertEqual(history.text_of(message), "one\ntwo")

    def test_text_of_tool_call_only_message(self):
        self.assertEqual(history.text_of(assistant(None, tool_calls=[{"id": "c"}])), "")

    def test_previous_turn_skips_current_prompt(self):
        self.assertEqual(history.previous_turn([user("why"), assistant("because"), user("now?")]),
                         ("why", "because"))

    def test_previous_turn_joins_across_tools(self):
        messages = [user("fix it"), assistant("Looking.", tool_calls=[{"id": "c"}]), tool("log"),
                    assistant(None, tool_calls=[{"id": "d"}]), tool("more"), assistant("Fixed."),
                    user("thanks")]
        self.assertEqual(history.previous_turn(messages), ("fix it", "Looking.\n\nFixed."))

    def test_previous_turn_without_assistant(self):
        self.assertEqual(history.previous_turn([user("first")]), ("", ""))


class NodeRunnerTest(unittest.TestCase):
    CHECK = REPO / "hooks" / "check.js"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="curt-hermes-"))

    def test_runs_the_cli(self):
        out = node_runner.run_json(self.CHECK, {"assistant": SLOP, "user": ""})
        self.assertIn("delve", [v["match"] for v in out])

    def test_missing_node_returns_none(self):
        with mock.patch.object(node_runner, "find_node", return_value=None):
            self.assertIsNone(node_runner.run_json(self.CHECK, {"assistant": SLOP}))

    def test_timeout_returns_none(self):
        slow = self.tmp / "slow.js"
        slow.write_text("setTimeout(() => {}, 5000);")
        with mock.patch.object(node_runner, "TIMEOUT_S", 0.2):
            self.assertIsNone(node_runner.run_json(slow, {}))

    def test_non_zero_exit_returns_none(self):
        failing = self.tmp / "fail.js"
        failing.write_text("process.exit(3);")
        self.assertIsNone(node_runner.run_json(failing, {}))

    def test_non_json_stdout_returns_none(self):
        noisy = self.tmp / "noisy.js"
        noisy.write_text("console.log('warning: something');")
        self.assertIsNone(node_runner.run_json(noisy, {}))


class RulesTest(unittest.TestCase):
    def test_file_op_reason_matches_the_shared_list(self):
        cases = json.loads((REPO / "tests" / "fileops.json").read_text())["cases"]
        for case in cases:
            with self.subTest(command=case["command"]):
                self.assertEqual(rules.file_op_reason(case["command"]), case["kind"])

    def test_file_op_reason_without_command(self):
        self.assertIsNone(rules.file_op_reason(None))
        self.assertIsNone(rules.file_op_reason(""))

    def test_every_kind_has_a_hermes_message(self):
        self.assertEqual(set(rules.HERMES_REASON), {"in_place", "redirect", "tee", "read"})

    def test_rule_target(self):
        self.assertEqual(rules.rule_target("terminal", {"command": "git commit -m 'x'"}), "commit")
        self.assertEqual(rules.rule_target("write_file", {"path": ".git/COMMIT_EDITMSG"}), "commit")
        self.assertEqual(rules.rule_target("patch", {"path": "docs/guide.md"}), "prose")
        self.assertEqual(rules.rule_target("write_file", {"path": "src/app.PY"}), "code")
        self.assertIsNone(rules.rule_target("write_file", {"path": "data.csv"}))
        self.assertIsNone(rules.rule_target("read_file", {"path": "src/app.py"}))
        self.assertIsNone(rules.rule_target("terminal", None))

    def test_read_rule_filters_markers(self):
        normal = rules.read_rule("core", auto=False)
        auto = rules.read_rule("core", auto=True)
        self.assertIn("Reach for the dedicated tool", normal)
        self.assertNotIn("Reach for the dedicated tool", auto)
        self.assertIn("Auto mode: Bash file operations are allowed", auto)
        self.assertNotIn("Auto mode: Bash file operations are allowed", normal)
        for text in (normal, auto):
            self.assertNotIn("curt:", text)
            self.assertNotIn("<!-- anti-slop:", text)

    def test_read_rule_missing_file(self):
        self.assertIsNone(rules.read_rule("no-such-rule", auto=False))

    def test_approvals_off(self):
        with mock.patch.dict(os.environ, {"HERMES_YOLO_MODE": "1"}):
            self.assertTrue(rules.approvals_off())
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HERMES_YOLO_MODE", None)
            with mock.patch.object(rules, "_approvals_mode", return_value="off"):
                self.assertTrue(rules.approvals_off())
            with mock.patch.object(rules, "_approvals_mode", return_value="smart"):
                self.assertFalse(rules.approvals_off())
            with mock.patch.object(rules, "_approvals_mode", side_effect=RuntimeError):
                self.assertFalse(rules.approvals_off())


class ReportTest(unittest.TestCase):
    V = [
        {"kind": "word", "match": "delve", "sentence": "Let us delve."},
        {"kind": "sycophancy", "match": "Great question", "sentence": "Great question!"},
    ]

    def test_previous_report_ranks_sycophancy_first(self):
        lines = report.previous_report(self.V)
        self.assertEqual(lines[0], "Response substance: possible editorial issues in your previous message:")
        self.assertEqual(lines[1], f'  Great question {report.DASH} "Great question!"')
        self.assertEqual(lines[2], "Word choice: possible editorial issues in your previous message:")
        self.assertTrue(lines[-1].startswith("These are heuristic matches."))

    def test_previous_report_truncates(self):
        many = [{"kind": "word", "match": f"w{i}", "sentence": f"s{i}"} for i in range(10)]
        lines = report.previous_report(many)
        self.assertIn("  ...and 2 more", lines)
        self.assertEqual(sum(line.startswith("  w") for line in lines), report.MAX_REPORTED)

    def test_midturn_report(self):
        text = report.midturn_report(self.V[:1])
        self.assertTrue(text.startswith("CURT: possible editorial issues in prose earlier in this turn:"))
        self.assertIn(f'  Word choice: delve {report.DASH} "Let us delve."', text)

    def test_key(self):
        self.assertEqual(report.key(self.V[0]), "word:delve:Let us delve.")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 .hermes-plugin/test_plugin.py`
Expected: FAIL at import with `ModuleNotFoundError: No module named 'curt_under_test.history'`.

- [ ] **Step 3: Implement the four modules**

Create `.hermes-plugin/node_runner.py`:

```python
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
    hermes_home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
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
        done = subprocess.run(
            [node, str(script), "--json"], input=json.dumps(payload),
            capture_output=True, text=True, timeout=TIMEOUT_S)
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
```

Create `.hermes-plugin/history.py`:

```python
"""Read the previous turn out of Hermes's OpenAI-format conversation history."""

TEXT_PARTS = {"text", "output_text", "input_text"}


def text_of(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and part.get("type") in TEXT_PARTS)
    return ""


def previous_turn(messages: list[dict]) -> tuple[str, str]:
    """(user_text, assistant_text) for the last turn that has an assistant reply.

    pre_llm_call receives the history with the new prompt already at the end, so
    the walk first skips back to the newest assistant message. One turn spans
    every assistant message after its user message; tool messages sit between
    them and carry no prose.
    """
    end = len(messages) - 1
    while end >= 0 and messages[end].get("role") != "assistant":
        end -= 1
    if end < 0:
        return "", ""
    start = end
    while start >= 0 and messages[start].get("role") != "user":
        start -= 1
    user_text = text_of(messages[start]) if start >= 0 else ""
    replies = [text_of(m).strip() for m in messages[start + 1:end + 1] if m.get("role") == "assistant"]
    return user_text, "\n\n".join(r for r in replies if r)
```

Create `.hermes-plugin/rules.py`:

```python
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
    except OSError:
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
```

Create `.hermes-plugin/report.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 .hermes-plugin/test_plugin.py`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add .hermes-plugin/
git commit -s -m "feat(hermes): rules, report text, history and node runner" -m "Pure helpers for the Hermes plugin. rules.py ports ruleTargetFor and fileOpReason; tests/fileops.json holds the file-op check equal to the Node version. report.py reproduces inject.js's finding text. history.py reads the previous turn from Hermes's conversation history, and node_runner.py runs check.js --json with a 2 second timeout."
```

---

### Task 3: Core rules section and the previous-reply hook

**Files:**
- Modify: `.hermes-plugin/__init__.py` (replace the placeholder)
- Create: `.hermes-plugin/plugin.yaml`
- Test: `.hermes-plugin/test_plugin.py`

**Interfaces:**
- Consumes: everything Task 2 produces.
- Produces:
  - `SECTION_MAX = 4000`; `REMIND_EVERY: int` (from `ANTI_SLOP_REMIND_EVERY`, default 9)
  - `class Session` with `prompts: int`, `last_reported: str | None`, `turn_id: str`, `user: dict[str, str]`, `interim: dict[str, list[str]]`, `seen: dict[str, list[str]]`, `injected: set[str]`
  - `_sessions: dict[str, Session]`; `session(session_id: str | None) -> Session`
  - `core_section(info: object) -> str`
  - `pre_llm_call(session_id=None, turn_id=None, user_message=None, conversation_history=None, is_first_turn=False, **_) -> dict | None`
  - `register(ctx)` (Task 4 adds three more hooks to it)

- [ ] **Step 1: Write the failing tests**

Add to `.hermes-plugin/test_plugin.py`, above `if __name__ == "__main__":`:

```python
class FakeCtx:
    def __init__(self):
        self.hooks = {}
        self.sections = {}

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_system_prompt_section(self, id, content, *, position="after_memory", max_chars=4000):
        self.sections[id] = (content, max_chars)


class PluginCase(unittest.TestCase):
    def setUp(self):
        PLUGIN._sessions.clear()
        patcher = mock.patch.object(rules, "approvals_off", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def prompt(self, messages, turn_id="t2", session_id="s1", first=False):
        result = PLUGIN.pre_llm_call(
            session_id=session_id, turn_id=turn_id, user_message=messages[-1]["content"],
            conversation_history=messages, is_first_turn=first)
        return result["context"] if result else None


class CoreSectionTest(PluginCase):
    def test_register_adds_the_core_section(self):
        ctx = FakeCtx()
        PLUGIN.register(ctx)
        content, max_chars = ctx.sections["curt.core"]
        self.assertEqual(max_chars, PLUGIN.SECTION_MAX)
        self.assertIn("Reach for the dedicated tool", content({}))

    def test_section_follows_approvals_off(self):
        with mock.patch.object(rules, "approvals_off", return_value=True):
            self.assertNotIn("Reach for the dedicated tool", PLUGIN.core_section({}))

    def test_oversized_core_moves_to_the_first_prompt(self):
        big = "x" * (PLUGIN.SECTION_MAX + 1)
        with mock.patch.object(rules, "read_rule", return_value=big):
            self.assertEqual(PLUGIN.core_section({}), "")
            self.assertTrue(self.prompt([user("hi")], first=True).startswith(big))
            self.assertIsNone(self.prompt([user("hi"), assistant(CLEAN), user("again")]))


class PreviousReplyTest(PluginCase):
    def test_register_wires_pre_llm_call(self):
        ctx = FakeCtx()
        PLUGIN.register(ctx)
        self.assertIs(ctx.hooks["pre_llm_call"], PLUGIN.pre_llm_call)

    def test_first_prompt_is_silent(self):
        self.assertIsNone(self.prompt([user("hi")], first=True))

    def test_slop_is_reported(self):
        text = self.prompt([user("why"), assistant(SLOP), user("ok")])
        self.assertIn("Response substance: possible editorial issues in your previous message:", text)
        self.assertIn("delve", text)
        self.assertTrue(text.rstrip().endswith("Continue the user's task."))

    def test_clean_reply_is_silent(self):
        self.assertIsNone(self.prompt([user("why"), assistant(CLEAN), user("ok")]))

    def test_same_turn_is_reported_once(self):
        messages = [user("why"), assistant(SLOP), user("ok")]
        self.assertIsNotNone(self.prompt(messages, turn_id="t2"))
        self.assertIsNone(self.prompt(messages, turn_id="t3"))

    def test_user_vocabulary_is_exempt(self):
        messages = [user("can we leverage the cache?"), assistant("We leverage the cache."), user("ok")]
        self.assertIsNone(self.prompt(messages))

    def test_findings_shown_mid_turn_are_dropped(self):
        PLUGIN.pre_llm_call(session_id="s1", turn_id="t1", user_message="why",
                            conversation_history=[user("why")], is_first_turn=True)
        s = PLUGIN.session("s1")
        s.seen["t1"] = [report.key({"kind": "word", "match": "delve",
                                    "sentence": "Let us delve into this robust solution."})]
        text = self.prompt([user("why"), assistant(SLOP), user("ok")], turn_id="t2")
        self.assertNotIn("delve", text)
        self.assertIn("Great question", text)

    def test_reminder_every_ninth_prompt(self):
        texts = [self.prompt([user(f"p{i}")], turn_id=f"t{i}") for i in range(1, 10)]
        self.assertEqual(texts[:8], [None] * 8)
        self.assertEqual(texts[8], report.SHORT)

    def test_reminder_cadence_reads_the_env(self):
        with mock.patch.object(PLUGIN, "REMIND_EVERY", 2):
            texts = [self.prompt([user(f"p{i}")], turn_id=f"t{i}") for i in range(1, 3)]
        self.assertEqual(texts, [None, report.SHORT])

    def test_empty_turn_ids_keep_the_current_turn(self):
        self.prompt([user("why")], turn_id="")
        PLUGIN.session("s1").interim[""] = ["kept"]
        self.prompt([user("why"), assistant(CLEAN), user("ok")], turn_id="")
        self.assertEqual(PLUGIN.session("s1").user[""], "ok")

    def test_node_missing_keeps_the_reminder(self):
        with mock.patch.object(node_runner, "find_node", return_value=None):
            texts = [self.prompt([user("why"), assistant(SLOP), user(f"p{i}")], turn_id=f"t{i}")
                     for i in range(1, 10)]
        self.assertEqual(texts[8], report.SHORT)

    def test_sessions_are_separate(self):
        self.prompt([user("why"), assistant(SLOP), user("ok")], session_id="a")
        self.assertIsNotNone(self.prompt([user("why"), assistant(SLOP), user("ok")], session_id="b"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 .hermes-plugin/test_plugin.py`
Expected: FAIL with `AttributeError: module 'curt_under_test' has no attribute '_sessions'`.

- [ ] **Step 3: Implement**

Replace `.hermes-plugin/__init__.py`:

```python
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
```

Create `.hermes-plugin/plugin.yaml`:

```yaml
name: curt
version: 0.6.0
description: Writing rules, prose lint and tool discipline for Hermes Agent
author: NovusEdge
provides_hooks:
  - pre_llm_call
  - on_interim_message
  - transform_tool_result
  - pre_tool_call
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 .hermes-plugin/test_plugin.py`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add .hermes-plugin/__init__.py .hermes-plugin/plugin.yaml .hermes-plugin/test_plugin.py
git commit -s -m "feat(hermes): core rules section and previous-reply lint" -m "core.md goes into a Hermes system-prompt section, which survives compression. pre_llm_call lints the previous turn once, drops findings already shown mid-turn, and restates the reminder every ANTI_SLOP_REMIND_EVERY prompts. A core.md over Hermes's 4,000 character section cap moves to the first prompt."
```

---

### Task 4: Mid-turn findings and the file-op guard

**Files:**
- Modify: `.hermes-plugin/__init__.py` (add three hooks, extend `register`)
- Test: `.hermes-plugin/test_plugin.py`

**Interfaces:**
- Consumes: Task 3's `Session`, `session()`, `_check()`; Task 2's `rules` and `report`.
- Produces:
  - `on_interim_message(text=None, turn_id=None, session_id=None, **_) -> None`
  - `transform_tool_result(tool_name=None, args=None, result=None, session_id=None, turn_id=None, **_) -> str | None`
  - `pre_tool_call(tool_name=None, args=None, **_) -> dict | None`

- [ ] **Step 1: Write the failing tests**

Add to `.hermes-plugin/test_plugin.py`, above `if __name__ == "__main__":`:

```python
class MidTurnTest(PluginCase):
    def tool_result(self, tool_name="terminal", args=None, result="ok", turn_id="t1"):
        return PLUGIN.transform_tool_result(
            tool_name=tool_name, args=args or {"command": "ls"}, result=result,
            session_id="s1", turn_id=turn_id)

    def interim(self, text, turn_id="t1"):
        PLUGIN.on_interim_message(text=text, already_streamed=False, turn_id=turn_id, session_id="s1")

    def test_register_wires_the_mid_turn_hooks(self):
        ctx = FakeCtx()
        PLUGIN.register(ctx)
        self.assertIs(ctx.hooks["on_interim_message"], PLUGIN.on_interim_message)
        self.assertIs(ctx.hooks["transform_tool_result"], PLUGIN.transform_tool_result)
        self.assertIs(ctx.hooks["pre_tool_call"], PLUGIN.pre_tool_call)

    def test_no_prose_and_no_rule_leaves_the_result(self):
        self.assertIsNone(self.tool_result())

    def test_interim_slop_is_appended(self):
        self.interim(SLOP)
        out = self.tool_result(result="exit 0")
        self.assertTrue(out.startswith("exit 0\n\nCURT: possible editorial issues in prose earlier in this turn:"))
        self.assertIn("Word choice: delve", out)

    def test_soft_findings_stay_out(self):
        self.interim(SOFT_ONLY)
        self.assertIsNone(self.tool_result())

    def test_a_finding_is_shown_once_per_turn(self):
        self.interim(SLOP)
        self.assertIsNotNone(self.tool_result())
        self.assertIsNone(self.tool_result())

    def test_rule_file_routes_once_per_session(self):
        first = self.tool_result("write_file", {"path": "src/app.py", "content": ""})
        self.assertIn(rules.read_rule("code", auto=False), first)
        self.assertIsNone(self.tool_result("patch", {"path": "src/other.py"}, turn_id="t2"))
        commit = self.tool_result("terminal", {"command": "git commit -m 'x'"})
        self.assertIn(rules.read_rule("commit", auto=False), commit)

    def test_non_string_result_is_untouched(self):
        self.interim(SLOP)
        self.assertIsNone(self.tool_result(result={"exit_code": 0}))

    def test_late_interim_is_caught_by_the_next_prompt(self):
        PLUGIN.pre_llm_call(session_id="s1", turn_id="t1", user_message="why",
                            conversation_history=[user("why")], is_first_turn=True)
        self.assertIsNone(self.tool_result())
        self.interim(SLOP)
        text = self.prompt([user("why"), assistant(SLOP), user("ok")], turn_id="t2")
        self.assertIn("delve", text)

    def test_node_missing_still_routes_rules(self):
        self.interim(SLOP)
        with mock.patch.object(node_runner, "find_node", return_value=None):
            out = self.tool_result("write_file", {"path": "notes.md"})
        self.assertIn(rules.read_rule("prose", auto=False), out)
        self.assertNotIn("CURT: possible editorial issues", out)


class GuardTest(PluginCase):
    def guard(self, command, tool_name="terminal"):
        return PLUGIN.pre_tool_call(tool_name=tool_name, args={"command": command}, session_id="s1")

    def test_ask_is_the_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTI_SLOP_TOOL_GUARD", None)
            out = self.guard("sed -i s/a/b/ app.py")
        self.assertEqual(out, {"action": "approve",
                               "message": "curt: " + rules.HERMES_REASON["in_place"]})

    def test_deny_blocks(self):
        with mock.patch.dict(os.environ, {"ANTI_SLOP_TOOL_GUARD": "deny"}):
            out = self.guard("cat src/main.go")
        self.assertEqual(out, {"action": "block", "message": "curt: " + rules.HERMES_REASON["read"]})

    def test_off_disables(self):
        with mock.patch.dict(os.environ, {"ANTI_SLOP_TOOL_GUARD": "off"}):
            self.assertIsNone(self.guard("sed -i s/a/b/ app.py"))

    def test_approvals_off_disables(self):
        with mock.patch.object(rules, "approvals_off", return_value=True):
            self.assertIsNone(self.guard("sed -i s/a/b/ app.py"))

    def test_harmless_command_passes(self):
        self.assertIsNone(self.guard("grep -rn foo src"))

    def test_other_tools_pass(self):
        self.assertIsNone(self.guard("sed -i s/a/b/ app.py", tool_name="execute_code"))

    def test_missing_args_pass(self):
        self.assertIsNone(PLUGIN.pre_tool_call(tool_name="terminal", args=None))
        self.assertIsNone(PLUGIN.pre_tool_call(tool_name="terminal", args={}))

    def test_internal_error_passes(self):
        with mock.patch.object(rules, "file_op_reason", side_effect=RuntimeError):
            self.assertIsNone(self.guard("sed -i s/a/b/ app.py"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 .hermes-plugin/test_plugin.py`
Expected: FAIL with `AttributeError: module 'curt_under_test' has no attribute 'transform_tool_result'`.

- [ ] **Step 3: Implement**

In `.hermes-plugin/__init__.py`, add before `def register(ctx):`:

```python
def on_interim_message(text=None, turn_id=None, session_id=None, **_):
    if text:
        session(session_id).interim.setdefault(turn_id or "", []).append(text)


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
        if target and target not in s.injected:
            text = rules.read_rule(target, rules.approvals_off())
            if text:
                blocks.append(text)
                s.injected.add(target)
        finding = _midturn_lint(s, turn_id or "")
        if finding:
            blocks.append(finding)
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
```

Extend `register`:

```python
def register(ctx):
    ctx.register_system_prompt_section("curt.core", core_section, max_chars=SECTION_MAX)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("on_interim_message", on_interim_message)
    ctx.register_hook("transform_tool_result", transform_tool_result)
    ctx.register_hook("pre_tool_call", pre_tool_call)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 .hermes-plugin/test_plugin.py && node hooks/selftest.js`
Expected: `OK`, then `selftest ok`.

- [ ] **Step 5: Commit**

```bash
git add .hermes-plugin/__init__.py .hermes-plugin/test_plugin.py
git commit -s -m "feat(hermes): mid-turn findings and the file-op guard" -m "transform_tool_result appends the routed rule file (once per session) and non-soft findings on the turn's interim prose to the tool result. pre_tool_call asks, blocks or stays off per ANTI_SLOP_TOOL_GUARD when a terminal command does a file tool's job, and stays off when Hermes approvals are off."
```

---

### Task 5: CI, docs and an end-to-end check

**Files:**
- Modify: `.github/workflows/ci.yml` (python job, after the `changelog extractor selftest` step)
- Modify: `README.md` (`## Install`, after `### Codex`)
- Modify: `docs/hooks.md` (new section)
- Modify: `docs/CHANGELOG.md`

- [ ] **Step 1: Add the CI step**

In `.github/workflows/ci.yml`, add to the `python` job after the `changelog extractor selftest` step. The plugin tests run `node`, which `ubuntu-latest` provides:

```yaml
      - name: Hermes plugin tests
        run: python3 .hermes-plugin/test_plugin.py
```

Extend the `lint own comments` step to cover the plugin:

```yaml
      - name: lint own comments
        run: python3 tools/lint.py --check --code tools/ hooks/ install.sh .hermes-plugin/
```

- [ ] **Step 2: Update the docs**

In `README.md`, add after the `### Codex` install section:

````markdown
### Hermes Agent

```bash
hermes plugins install NovusEdge/curt --enable
```

The core rules load into every new Hermes session. The previous-reply lint, mid-turn findings and the file-op guard run as Hermes hooks. Prose lint runs `hooks/check.js` with `node`, from `PATH` or the copy Hermes installs in `~/.hermes/node`; without node, the rules and the guard still work. Skills are not part of the Hermes plugin: point Hermes's `skills.external_dirs` at this repo's `skills/` to use them.
````

In `docs/hooks.md`, add a section at the end:

```markdown
## Hermes Agent

The plugin in `.hermes-plugin/` maps each hook onto Hermes:

| Claude Code | Hermes |
|---|---|
| SessionStart, SubagentStart | system-prompt section `curt.core`, kept through compression |
| UserPromptSubmit | `pre_llm_call` |
| PostToolUse | `on_interim_message` collects the turn's prose; `transform_tool_result` appends rule files and findings to the tool result |
| PreToolUse on Bash | `pre_tool_call` on `terminal`; `ask` maps to Hermes's approval prompt, `deny` to a block |

Hermes delivers interim messages on a background queue, so prose written just before a fast tool call can miss the mid-turn check. The next prompt's lint covers the whole previous turn and reports it then.

The guard is off when Hermes runs without approvals (`--yolo` or `approvals.mode: off`), the counterpart of auto mode. Its messages name Hermes's `patch`, `write_file` and `read_file` tools.

Run the plugin tests with `python3 .hermes-plugin/test_plugin.py`.
```

In `docs/CHANGELOG.md`, add above `## [0.6.0]`:

```markdown
## [Unreleased]

### Added

- A Hermes Agent plugin in `.hermes-plugin/`. Install it with `hermes plugins install NovusEdge/curt --enable`. The core rules, previous-reply lint, mid-turn findings and the file-op guard carry over; skills do not.
- `node hooks/check.js --json`, for hosts that pass message text instead of a transcript.
- `tests/fileops.json`, shared by the Node and Python file-op checks.
```

- [ ] **Step 3: Run every local check CI runs**

Run:

```bash
python3 tools/lint.py --selftest && python3 .hermes-plugin/test_plugin.py && node hooks/selftest.js \
  && python3 tools/lint.py --check README.md docs/CONTRIBUTING.md docs/CHANGELOG.md docs/hooks.md docs/linting.md \
  && python3 tools/lint.py --check --code tools/ hooks/ install.sh .hermes-plugin/ \
  && ! grep -rn "$(printf '\342\200\224')" README.md docs/
```

Expected: every command succeeds and the final `grep` finds nothing. If `lint.py --check --code` flags a comment in `.hermes-plugin/`, fix the comment, not the linter.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml README.md docs/hooks.md docs/CHANGELOG.md
git commit -s -m "docs: Hermes Agent install and hook mapping" -m "CI runs the plugin tests and lints the plugin's comments."
```

- [ ] **Step 5: End-to-end check in Hermes (by hand)**

Run, in a terminal outside any Claude Code session:

```bash
hermes plugins install file://$HOME/Projects/curt --enable
hermes -z 'Reply with exactly this sentence and nothing else: Great question! Let us delve into this robust solution.'
hermes -c -z 'thanks'
hermes -z 'Use the terminal tool to run: cat README.md'
grep -nE "Response substance|curt: use read_file" ~/.hermes/logs/agent.log | tail -5
```

Expected: the plugin installs and enables. The `thanks` request carries `Response substance: possible editorial issues in your previous message:`. The `cat README.md` call reaches Hermes's approval prompt (or is denied in one-shot mode, per `approvals.single_query_mode: deny`) with `curt: use read_file to read a file instead of cat, head, or tail.`. If the log does not record injected context, confirm from the session transcript instead, and note which source showed it in the PR description.
