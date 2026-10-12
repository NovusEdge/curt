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

    def test_text_of_none_text_part(self):
        message = {"role": "assistant", "content": [
            {"type": "text", "text": None}, {"type": "output_text", "text": "kept"}]}
        self.assertEqual(history.text_of(message), "\nkept")

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
        with mock.patch.object(node_runner, "find_node", return_value=None), \
                mock.patch.object(node_runner, "_warned_missing", False), \
                self.assertLogs(node_runner.logger, "WARNING"):
            self.assertIsNone(node_runner.run_json(self.CHECK, {"assistant": SLOP}))

    def test_invalid_utf8_output_returns_none(self):
        bad = self.tmp / "bad.js"
        bad.write_text("process.stdout.write(Buffer.from([0xff, 0xfe]));")
        self.assertIsNone(node_runner.run_json(bad, {}))

    def test_unserializable_payload_returns_none(self):
        self.assertIsNone(node_runner.run_json(self.CHECK, {"assistant": object()}))

    def test_no_home_directory_returns_none(self):
        with mock.patch.object(node_runner.shutil, "which", return_value=None), \
                mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.object(node_runner.Path, "home", side_effect=RuntimeError), \
                mock.patch.object(node_runner, "_warned_missing", True):
            os.environ.pop("HERMES_HOME", None)
            self.assertIsNone(node_runner.find_node())
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
