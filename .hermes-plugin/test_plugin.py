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

    def test_read_rule_invalid_utf8(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "core.md").write_bytes(b"\xff\xfe")
            with mock.patch.object(rules, "RULES_DIR", Path(d)):
                self.assertIsNone(rules.read_rule("core", auto=False))

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

    def test_reminder_cadence_follows_remind_every(self):
        with mock.patch.object(PLUGIN, "REMIND_EVERY", 2):
            texts = [self.prompt([user(f"p{i}")], turn_id=f"t{i}") for i in range(1, 3)]
        self.assertEqual(texts, [None, report.SHORT])

    def test_disabled_reminder_never_fires(self):
        # "0" and "abc" both parse to 0.
        with mock.patch.object(PLUGIN, "REMIND_EVERY", PLUGIN.parse_remind_every("abc")):
            texts = [self.prompt([user(f"p{i}")], turn_id=f"t{i}") for i in range(1, 12)]
        self.assertEqual(texts, [None] * 11)

    def test_parse_remind_every(self):
        parse = PLUGIN.parse_remind_every
        self.assertEqual(
            [parse(v) for v in (None, "", "4", "0", "-3", "abc", "2.5")],
            [9, 9, 4, 0, 0, 0, 0])

    def test_empty_turn_ids_keep_the_current_turn(self):
        self.prompt([user("why")], turn_id="")
        PLUGIN.session("s1").interim[""] = ["kept"]
        self.prompt([user("why"), assistant(CLEAN), user("ok")], turn_id="")
        self.assertEqual(PLUGIN.session("s1").user[""], "ok")
        self.assertNotIn("", PLUGIN.session("s1").interim)

    def test_unexpected_errors_never_escape(self):
        with mock.patch.object(rules, "read_rule", side_effect=ValueError("boom")):
            self.assertIsNone(self.prompt([user("hi")], first=True))

    def test_node_missing_keeps_the_reminder(self):
        with mock.patch.object(node_runner, "find_node", return_value=None), \
                mock.patch.object(node_runner, "_warned_missing", False), \
                self.assertLogs(node_runner.logger, "WARNING"):
            texts = [self.prompt([user("why"), assistant(SLOP), user(f"p{i}")], turn_id=f"t{i}")
                     for i in range(1, 10)]
        self.assertEqual(texts[8], report.SHORT)

    def test_sessions_are_separate(self):
        self.prompt([user("why"), assistant(SLOP), user("ok")], session_id="a")
        self.assertIsNotNone(self.prompt([user("why"), assistant(SLOP), user("ok")], session_id="b"))


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
        with mock.patch.object(node_runner, "find_node", return_value=None), \
                mock.patch.object(node_runner, "_warned_missing", False), \
                self.assertLogs(node_runner.logger, "WARNING"):
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


if __name__ == "__main__":
    unittest.main()
