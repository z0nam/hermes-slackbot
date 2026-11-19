"""Stdlib tests for scripts/remind.py (no Hermes, no network)."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("remind", ROOT / "scripts/remind.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Remind(unittest.TestCase):
    rm = load()

    def test_script_prints_text_verbatim_even_with_quotes_and_newlines(self):
        text = "⏰ 도청에 \"v4\" 보내기\n둘째 줄 '따옴표' \\ 끝"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "j.py"
            p.write_text(self.rm.script_body(text), encoding="utf-8")
            out = subprocess.run([sys.executable, str(p)], capture_output=True,
                                 env=dict(os.environ, PYTHONIOENCODING="ascii")).stdout.decode("utf-8")
        self.assertEqual(out.rstrip("\r\n"), text)

    def test_job_name_is_short_single_line(self):
        self.assertEqual(self.rm.job_name("a\n b"), "remind: a b")
        self.assertTrue(self.rm.job_name("x" * 100).endswith("…"))

    def _main(self, *argv, run=None):
        with tempfile.TemporaryDirectory() as d:
            calls = []
            def fake(*args):
                calls.append(args)
                if args[:2] == ("config", "env-path"):
                    return str(Path(d) / ".env")
                return run(*args) if run else "Created job"
            with mock.patch.object(sys, "argv", ["remind.py", *argv]), \
                    mock.patch.object(self.rm.install, "run", fake), mock.patch("builtins.print"):
                self.rm.main()
            return calls, sorted((Path(d) / "scripts" / "remind").glob("*.py"))

    def test_registers_one_shot_no_agent_slack_job(self):
        calls, files = self._main("in 30m", "회의")
        cron = calls[-1]
        self.assertEqual(cron[:3], ("cron", "create", "in 30m"))
        for flag in ("--no-agent", "--deliver"):
            self.assertIn(flag, cron)
        self.assertEqual(cron[cron.index("--deliver") + 1], "slack")
        self.assertEqual(cron[cron.index("--script") + 1], "remind/" + files[0].name)

    def test_rejects_recurring_and_empty(self):
        for argv in (("every 1h", "x"), ("30m", "x"), ("0 9 * * *", "x"), ("in 5m", "  ")):
            with self.assertRaises(SystemExit):
                self._main(*argv)

    def test_failed_cron_create_leaves_no_script(self):
        def boom(*args):
            raise SystemExit("cron failed")
        with tempfile.TemporaryDirectory() as d:
            def fake(*args):
                return str(Path(d) / ".env") if args[:2] == ("config", "env-path") else boom()
            with mock.patch.object(sys, "argv", ["remind.py", "in 5m", "x"]), \
                    mock.patch.object(self.rm.install, "run", fake), self.assertRaises(SystemExit):
                self.rm.main()
            self.assertEqual(list((Path(d) / "scripts" / "remind").glob("*.py")), [])


if __name__ == "__main__":
    unittest.main()
