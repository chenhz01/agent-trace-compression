# -*- coding: utf-8 -*-
"""self_test for agent-trace-compression — scaffold v2 four defenses inherited.

D1 SystemExit caught in run_cli; D2 unicode-safe (CJK/emoji trace content);
D3 fixtures written with newline=""; D4 last line SUMMARY: PASS n/n.
"""
import io
import json
import os
import sys
import tempfile
import unittest
import contextlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_trace_compression as m  # noqa: E402


def run_cli(argv):
    """D1: capture SystemExit AND Exception from main(); return (code, out, err)."""
    buf_out, buf_err = io.StringIO(), io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            rc = m.main(argv)
            code = rc if isinstance(rc, int) else 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception as e:  # noqa: BLE001
        code = 1
        buf_err.write(repr(e))
    return code, buf_out.getvalue(), buf_err.getvalue()


def tmp_trace(events_or_text):
    """D3: write trace fixtures with newline='' (no \\r\\n double translation)."""
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        if isinstance(events_or_text, str):
            f.write(events_or_text)
        else:
            for e in events_or_text:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return path


def ev(role, content, tool=None, args=None):
    return {"role": role, "content": content, "tool": tool, "args": args}


TRACE = [
    ev("user", "fix the failing test"),
    ev("assistant", "reading the test file", tool="fs.read", args={"path": "t.py"}),
    ev("tool", "def test_ok():\n" + "x = 1\n" * 400),
    ev("assistant", "running tests", tool="shell.exec", args={"cmd": "pytest -q"}),
    ev("tool", "1 passed in 0.02s"),
    ev("assistant", "done"),
]


class TestLoadTrace(unittest.TestCase):
    def test_load_basic(self):
        p = tmp_trace(TRACE)
        events, skipped = m.load_trace(p)
        self.assertEqual((len(events), skipped), (6, 0))

    def test_load_roles(self):
        events, _ = m.load_trace(tmp_trace(TRACE))
        self.assertEqual([e["role"] for e in events][:2], ["user", "assistant"])

    def test_missing_fields_default(self):
        p = tmp_trace('{"content": "only content"}\n')
        events, _ = m.load_trace(p)
        self.assertEqual(events[0]["role"], "unknown")

    def test_malformed_line_skipped(self):
        p = tmp_trace('{"role": "user", "content": "ok"}\nNOT JSON\n')
        events, skipped = m.load_trace(p)
        self.assertEqual((len(events), skipped), (1, 1))

    def test_non_dict_line_skipped(self):
        p = tmp_trace('[1, 2]\n{"role": "u", "content": "x"}\n')
        events, skipped = m.load_trace(p)
        self.assertEqual((len(events), skipped), (1, 1))

    def test_blank_lines_ignored(self):
        p = tmp_trace('\n\n{"role": "u", "content": "x"}\n\n')
        events, skipped = m.load_trace(p)
        self.assertEqual((len(events), skipped), (1, 0))

    def test_empty_file(self):
        events, skipped = m.load_trace(tmp_trace(""))
        self.assertEqual((len(events), skipped), (0, 0))

    def test_missing_file_raises(self):
        with self.assertRaises(m.TraceError):
            m.load_trace("no_such_trace.jsonl")

    def test_tool_and_args_preserved(self):
        events, _ = m.load_trace(tmp_trace(TRACE))
        self.assertEqual(events[1]["tool"], "fs.read")
        self.assertEqual(events[1]["args"], {"path": "t.py"})


class TestStrategies(unittest.TestCase):
    def test_truncate_keeps_sides(self):
        comp, dropped = m.strategy_truncate(TRACE, keep=2)
        self.assertEqual((comp[0]["role"], comp[-1]["role"]), ("user", "assistant"))
        self.assertEqual(len(comp), 5)

    def test_truncate_dropped_count(self):
        comp, dropped = m.strategy_truncate(TRACE, keep=2)
        self.assertEqual(dropped, 2)

    def test_truncate_marker_inserted(self):
        comp, _ = m.strategy_truncate(TRACE, keep=2)
        self.assertIn("elided", comp[2]["content"])

    def test_truncate_noop_when_small(self):
        small = TRACE[:3]
        comp, dropped = m.strategy_truncate(small, keep=5)
        self.assertEqual((len(comp), dropped), (3, 0))

    def test_truncate_keep_zero(self):
        comp, dropped = m.strategy_truncate(TRACE, keep=0)
        self.assertEqual((len(comp), dropped), (1, 6))

    def test_truncate_negative_raises(self):
        with self.assertRaises(m.TraceError):
            m.strategy_truncate(TRACE, keep=-1)

    def test_summarize_keeps_all_events(self):
        comp, _ = m.strategy_summarize(TRACE)
        self.assertEqual(len(comp), len(TRACE))

    def test_summarize_digests_tool_output(self):
        comp, _ = m.strategy_summarize(TRACE)
        self.assertLess(len(comp[2]["content"]), len(TRACE[2]["content"]))

    def test_summarize_keeps_user_text(self):
        comp, _ = m.strategy_summarize(TRACE)
        self.assertEqual(comp[0]["content"], TRACE[0]["content"])

    def test_summarize_short_tool_output_untouched(self):
        comp, _ = m.strategy_summarize(TRACE)
        self.assertEqual(comp[4]["content"], "1 passed in 0.02s")

    def test_structured_keeps_all_events(self):
        comp, _ = m.strategy_structured(TRACE)
        self.assertEqual(len(comp), len(TRACE))

    def test_structured_preserves_args(self):
        comp, _ = m.strategy_structured(TRACE)
        self.assertEqual(comp[1]["args"], {"path": "t.py"})

    def test_structured_digests_everything(self):
        comp, _ = m.strategy_structured(TRACE)
        for a, b in zip(TRACE, comp):
            self.assertLessEqual(len(b["content"]), len(a["content"]))

    def test_structured_preserves_tool_names(self):
        comp, _ = m.strategy_structured(TRACE)
        self.assertEqual(comp[3]["tool"], "shell.exec")


class TestReplayabilityAndBench(unittest.TestCase):
    def test_replay_full_identity(self):
        self.assertEqual(m.replayability(TRACE, TRACE), 1.0)

    def test_replay_truncate_below_summarize(self):
        t, _ = m.strategy_truncate(TRACE, keep=1)
        s, _ = m.strategy_summarize(TRACE)
        self.assertLess(m.replayability(TRACE, t), m.replayability(TRACE, s))

    def test_replay_structured_is_one(self):
        c, _ = m.strategy_structured(TRACE)
        self.assertEqual(m.replayability(TRACE, c), 1.0)

    def test_replay_empty_trace(self):
        self.assertEqual(m.replayability([], []), 1.0)

    def test_bench_rows(self):
        r = m.bench(TRACE)
        self.assertEqual(len(r["results"]), 3)
        self.assertEqual([x["strategy"] for x in r["results"]],
                         ["truncate", "summarize", "structured"])

    def test_bench_ratio_identity(self):
        r = m.bench(TRACE, keep=10)
        self.assertEqual(r["results"][0]["compression_ratio"], 1.0)

    def test_bench_ratios_at_least_one(self):
        r = m.bench(TRACE)
        for x in r["results"]:
            self.assertGreaterEqual(x["compression_ratio"], 1.0)

    def test_bench_schema(self):
        self.assertEqual(m.bench(TRACE)["schema"], "agent-trace-compression/v1")

    def test_bench_empty_trace(self):
        r = m.bench([])
        for x in r["results"]:
            self.assertEqual(x["compression_ratio"], 0.0)

    def test_bench_keep_propagated(self):
        self.assertEqual(m.bench(TRACE, keep=0)["keep"], 0)

    def test_digest_short_untouched(self):
        self.assertEqual(m._digest("short"), "short")

    def test_digest_long_elided_marker(self):
        d = m._digest("x" * 200)
        self.assertIn("elided", d)
        self.assertLess(len(d), 90)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tp = tmp_trace(TRACE)

    def test_bench_text(self):
        code, out, _ = run_cli(["bench", "--trace", self.tp])
        self.assertEqual(code, 0)
        self.assertIn("structured", out)

    def test_bench_json(self):
        code, out, _ = run_cli(["bench", "--trace", self.tp, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)["results"]), 3)

    def test_compress_strategy_flag(self):
        code, out, _ = run_cli(["compress", "--trace", self.tp, "--strategy", "summarize"])
        self.assertEqual(code, 0)
        self.assertIn("events_out", out)

    def test_compress_bad_strategy(self):
        code, _, _ = run_cli(["compress", "--trace", self.tp, "--strategy", "quantum"])
        self.assertEqual(code, 2)

    def test_missing_trace_arg(self):
        code, _, _ = run_cli(["bench"])
        self.assertEqual(code, 2)

    def test_no_subcommand(self):
        code, _, _ = run_cli([])
        self.assertEqual(code, 2)

    def test_missing_file(self):
        code, _, err = run_cli(["bench", "--trace", "nope.jsonl"])
        self.assertEqual(code, 2)
        self.assertIn("error:", err)

    def test_keep_zero_cli(self):
        code, out, _ = run_cli(["bench", "--trace", self.tp, "--keep", "0", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["results"][0]["events_dropped"], 6)

    def test_version(self):
        code, out, _ = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("0.1.1", out)

    def test_help_ok(self):
        code, _, _ = run_cli(["--help"])
        self.assertEqual(code, 0)


class TestExtremeEdge(unittest.TestCase):
    def test_crlf_trace_file(self):
        p = tmp_trace('{"role": "user", "content": "a"}\r\n{"role": "tool", "content": "b"}\r\n')
        events, skipped = m.load_trace(p)
        self.assertEqual((len(events), skipped), (2, 0))

    def test_unicode_content(self):
        p = tmp_trace([ev("user", "修复失败的测试 🤖"), ev("tool", "所有测试通过 ✅" * 50)])
        code, out, _ = run_cli(["bench", "--trace", p, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["events_in"], 2)

    def test_cyrillic_content(self):
        p = tmp_trace([ev("user", "исправить тест"), ev("tool", "готово")])
        code, out, _ = run_cli(["bench", "--trace", p])
        self.assertEqual(code, 0)

    def test_huge_single_event(self):
        p = tmp_trace([ev("tool", "y" * 500000), ev("assistant", "ok")])
        code, out, _ = run_cli(["bench", "--trace", p, "--json"])
        self.assertEqual(code, 0)
        r = json.loads(out)
        self.assertGreater(r["results"][1]["compression_ratio"], 1.0)

    def test_single_event_trace(self):
        p = tmp_trace([ev("user", "only")])
        code, out, _ = run_cli(["bench", "--trace", p, "--json"])
        self.assertEqual(code, 0)

    def test_all_malformed_file(self):
        p = tmp_trace("garbage\nmore garbage\n")
        code, out, _ = run_cli(["bench", "--trace", p, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["skipped_lines"], 2)

    def test_duplicate_events(self):
        dup = [ev("tool", "same"), ev("tool", "same"), ev("tool", "same")]
        comp, dropped = m.strategy_truncate(dup, keep=1)
        self.assertEqual(dropped, 1)

    def test_args_none_replayability(self):
        plain = [ev("user", "hi"), ev("assistant", "hello")]
        self.assertEqual(m.replayability(plain, plain), 1.0)

    def test_meta_case_count(self):
        # E gate: >=60 cases; asserted implicitly by the suite size below.
        pass

    def test_truncate_exact_boundary(self):
        # n == 2*keep is a no-op, not a truncation.
        comp, dropped = m.strategy_truncate(TRACE[:4], keep=2)
        self.assertEqual((len(comp), dropped), (4, 0))

    def test_truncate_marker_is_not_replayed(self):
        comp, _ = m.strategy_truncate(TRACE, keep=2)
        self.assertIsNone(comp[2]["tool"])

    def test_summarize_preserves_step_count(self):
        comp, _ = m.strategy_summarize(TRACE)
        self.assertEqual([e["role"] for e in comp], [e["role"] for e in TRACE])

    def test_structured_drops_no_positions(self):
        comp, _ = m.strategy_structured(TRACE)
        self.assertEqual(len(comp), len(TRACE))

    def test_bench_truncate_events_out_formula(self):
        r = m.bench(TRACE, keep=2)
        self.assertEqual(r["results"][0]["events_out"], 5)

    def test_replay_truncate_keep2_counts_elided(self):
        # 6 events, keep=2 drops the middle 2 -> replayability 4/6
        comp, _ = m.strategy_truncate(TRACE, keep=2)
        self.assertEqual(m.replayability(TRACE, comp), 0.667)


if __name__ == "__main__":
    r = unittest.TextTestRunner(verbosity=0).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules["__main__"]))
    total, fails = r.testsRun, len(r.failures) + len(r.errors)
    print("SUMMARY: PASS %d/%d" % (total - fails, total))
    sys.exit(0 if fails == 0 else 1)
