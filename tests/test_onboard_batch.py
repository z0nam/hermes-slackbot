import io
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import onboard_batch as ob  # noqa: E402

CODE_A = "JX-" + "A" * 26
CODE_B = "JX-" + "B2" * 13

ROSTER = "이름\t메일\t슬랙 UID\t비고\n가가\ta@x\tU0AAAAAAAA1\t\n나나\tb@x\tU0BBBBBBBB2\t\n다다\tc@x\tU0CCCCCCCC3\t\n가가2\ta@x\tU0AAAAAAAA1\t\n"
REG = {"aa": {"app_id": "A0AAAAAAAAA", "user": "U0AAAAAAAA1", "created": "x"},
       "bb": {"app_id": "A0BBBBBBBBB", "user": "U0BBBBBBBB2", "created": "x"},
       "zz": {"app_id": "A0ZZZZZZZZZ", "user": "U0ZZZZZZZZ9", "created": "x"}}


class Pure(unittest.TestCase):
    def test_roster_tsv_and_csv(self):
        self.assertEqual(ob.parse_roster(ROSTER), [("가가", "U0AAAAAAAA1"), ("나나", "U0BBBBBBBB2"), ("다다", "U0CCCCCCCC3")])
        self.assertEqual(ob.parse_roster("name,uid\n라라,U0DDDDDDDD4\n,\n"), [("라라", "U0DDDDDDDD4")])

    def test_plan_roster_order_missing_and_done(self):
        roster = ob.parse_roster(ROSTER)
        todo, missing = ob.plan(roster, REG, {"aa": {"status": "done"}})
        self.assertEqual([t[1] for t in todo], ["bb"])          # done skipped, zz not in roster
        self.assertEqual(missing, ["다다"])
        todo, _ = ob.plan(roster, REG, {"aa": {"status": "skipped"}})
        self.assertEqual([t[1] for t in todo], ["aa", "bb"])    # skipped people are asked again
        todo, _ = ob.plan(roster, REG, {"aa": {"status": "done"}}, only={"aa"})
        self.assertEqual([t[1] for t in todo], ["aa"])          # --only redoes a done person

    def test_find_code_takes_last(self):
        self.assertEqual(ob.find_code(f"x {CODE_A}\n  {CODE_B}\n"), CODE_B)
        self.assertIsNone(ob.find_code("JX-short"))


class Walk(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.progress_path = self.tmp / "progress.json"
        self.codes = self.tmp / "codes.txt"
        self.out = []
        self.opened = []
        self.calls = []

    def run_walk(self, todo, answers, results):
        answers, results = iter(answers), iter(results)

        def handoff(jaix, ident, user, again=False, echo=print):
            self.calls.append((ident, user, again))
            return next(results)
        progress = {}
        n = ob.walk(todo, ["jaix"], self.progress_path, progress, self.codes, ask=lambda _: next(answers),
                    open_url=self.opened.append, echo=lambda *a, **k: self.out.append(" ".join(map(str, a))),
                    handoff=handoff)
        return n, progress

    def todo(self):
        return [("가가", "aa", REG["aa"]), ("나나", "bb", REG["bb"])]

    def test_done_skip_and_codes_file_0600(self):
        n, progress = self.run_walk(self.todo(), ["", "", "", "s"], [(0, CODE_A)])
        self.assertEqual(n, 1)
        self.assertEqual(progress["aa"]["status"], "done")
        self.assertEqual(progress["bb"]["status"], "skipped")
        self.assertEqual(self.codes.read_text(encoding="utf-8"), f"가가 · {CODE_A}\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.codes).st_mode), 0o600)
        self.assertEqual(self.opened, ["https://api.slack.com/apps/A0AAAAAAAAA/install-on-team",
                                       "https://api.slack.com/apps/A0AAAAAAAAA/general",
                                       "https://api.slack.com/apps/A0AAAAAAAAA/oauth"])
        self.assertEqual(ob.load_progress(self.progress_path), progress)  # persisted for resume

    def test_quit_stops_before_next(self):
        n, progress = self.run_walk(self.todo(), ["q"], [])
        self.assertEqual((n, progress, self.calls), (0, {}, []))

    def test_already_issued_needs_explicit_again(self):
        n, progress = self.run_walk(self.todo()[:1], ["", "", "", "n"], [(3, None)])
        self.assertEqual(self.calls, [("aa", "U0AAAAAAAA1", False)])     # no silent --again
        self.assertEqual(progress["aa"]["status"], "skipped")
        self.assertFalse(self.codes.exists())
        n, progress = self.run_walk(self.todo()[:1], ["", "", "", "y"], [(3, None), (0, CODE_B)])
        self.assertEqual(self.calls[-1], ("aa", "U0AAAAAAAA1", True))
        self.assertEqual(progress["aa"]["status"], "done")

    def test_failure_retry_then_skip(self):
        n, progress = self.run_walk(self.todo()[:1], ["", "", "", "r", "x"], [(1, None), (0, None)])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(progress["aa"]["status"], "skipped")   # exit 0 but no code is not success


class RunHandoff(unittest.TestCase):
    def test_pipes_stdout_only_and_finds_code(self):
        tmp = Path(tempfile.mkdtemp())
        fake = tmp / "fake_jaix.py"
        fake.write_text(textwrap.dedent(f"""
            import sys
            print("args", sys.argv[1:])
            print("  {CODE_A}")
            sys.exit(0)
        """), encoding="utf-8")
        seen = io.StringIO()
        rc, code = ob.run_handoff([sys.executable, str(fake)], "aa", "U0AAAAAAAA1", again=True,
                                  echo=lambda s, end="", flush=False: seen.write(s))
        self.assertEqual((rc, code), (0, CODE_A))
        self.assertIn("['hermes', 'handoff', 'aa', '--user', 'U0AAAAAAAA1', '--again']", seen.getvalue())

    def test_main_reports_missing_and_nothing_to_do(self):
        tmp = Path(tempfile.mkdtemp())
        roster = tmp / "r.tsv"
        roster.write_text(ROSTER, encoding="utf-8")
        old = ob.provision_app.load_registry, ob.provision_app.CONF
        ob.provision_app.load_registry, ob.provision_app.CONF = (lambda: {}), tmp
        try:
            out = io.StringIO()
            sys.stdout, real = out, sys.stdout
            try:
                self.assertEqual(ob.main(["--roster", str(roster)]), 0)
            finally:
                sys.stdout = real
        finally:
            ob.provision_app.load_registry, ob.provision_app.CONF = old
        self.assertIn("앱이 없는 사람 3명", out.getvalue())


if __name__ == "__main__":
    unittest.main()
