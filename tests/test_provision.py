"""Stdlib tests for the admin provisioning flow (scripts/provision_app.py, scripts/setup_pc.py).
No network: Slack calls are replaced with fakes."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


def load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Provision(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["HERMES_SLACKBOT_CONF"] = self.tmp.name  # forces the file store, never the Keychain
        self.pa = load("scripts/provision_app.py", "provision_app")

    def tearDown(self):
        del os.environ["HERMES_SLACKBOT_CONF"]
        self.tmp.cleanup()

    def test_rotation_stores_new_refresh_before_use(self):
        self.pa.save_refresh("xoxe-old")
        seen = []

        def fake(method, **p):
            seen.append((method, p))
            return {"ok": True, "token": "xoxe.xoxp-access", "refresh_token": "xoxe-new"}

        with mock.patch.object(self.pa, "call", fake):
            self.assertEqual(self.pa.access_token(), "xoxe.xoxp-access")
        self.assertEqual(seen, [("tooling.tokens.rotate", {"refresh_token": "xoxe-old"})])
        self.assertEqual(self.pa.load_refresh(), "xoxe-new")
        self.assertEqual(oct(Path(self.tmp.name, "config-refresh-token").stat().st_mode & 0o777), "0o600")

    def test_rotation_failure_keeps_old_token(self):
        self.pa.save_refresh("xoxe-old")
        with mock.patch.object(self.pa, "call", lambda m, **p: {"ok": False, "error": "invalid_refresh_token"}):
            with self.assertRaises(SystemExit):
                self.pa.access_token()
        self.assertEqual(self.pa.load_refresh(), "xoxe-old")

    def test_create_registers_app(self):
        self.pa.save_refresh("xoxe-1")
        calls = []

        def fake(method, **p):
            calls.append(method)
            if method == "tooling.tokens.rotate":
                return {"ok": True, "token": "t", "refresh_token": "xoxe-2"}
            if method == "apps.manifest.create":
                self.assertEqual(json.loads(p["manifest"])["display_information"]["name"], "Hermes-alice")
                return {"ok": True, "app_id": "A1", "credentials": {"client_secret": "SECRET-xyz"}}
            return {"ok": True}

        manifest = {"display_information": {"name": "Hermes"}, "features": {"slash_commands": []}}
        with mock.patch.object(self.pa, "call", fake), \
                mock.patch.object(self.pa.make_manifest, "hermes_manifest", lambda n, d: manifest), \
                mock.patch("builtins.print"):
            self.pa.cmd_create(NS(id="Alice", user="U1", force=False))
        self.assertEqual(calls, ["tooling.tokens.rotate", "apps.manifest.validate", "apps.manifest.create"])
        reg = self.pa.load_registry()
        self.assertEqual(reg["alice"]["app_id"], "A1")
        self.assertNotIn("SECRET-xyz", json.dumps(reg))  # app secrets are not kept
        with mock.patch.object(self.pa, "call", fake), self.assertRaises(SystemExit):
            self.pa.cmd_create(NS(id="alice", user="U1", force=False))  # already registered

    def test_call_waits_out_rate_limit(self):
        import io
        import urllib.error
        hits, slept = [], []

        def urlopen(req, timeout):
            hits.append(req.full_url)
            if len(hits) == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "7"}, None)
            return io.BytesIO(b'{"ok": true}')

        with mock.patch.object(self.pa.urllib.request, "urlopen", urlopen), \
                mock.patch.object(self.pa.time, "sleep", slept.append), mock.patch("sys.stderr"):
            self.assertEqual(self.pa.call("apps.manifest.update", app_id="A1"), {"ok": True})
        self.assertEqual(len(hits), 2)
        self.assertEqual(slept, [7])

    def test_changed_paths(self):
        old = {"a": {"b": 1, "c": [1]}, "d": 1}
        new = {"a": {"b": 2, "c": [1]}, "e": 1}
        self.assertEqual(self.pa.changed_paths(old, new), ["/a/b", "/d", "/e"])
        self.assertEqual(self.pa.changed_paths(old, old), [])

    def test_setup_line_runs_setup_pc_with_id_and_user(self):
        line = self.pa.setup_line("alice", "U123")
        self.assertIn("setup_pc.py\" alice --user U123", line)
        self.assertIn("archive/refs/heads/main.zip", line)
        self.assertNotIn("\n", line)  # one paste in PowerShell


class SetupPc(unittest.TestCase):
    sp = load("scripts/setup_pc.py", "setup_pc")

    def test_bot_name_matches(self):
        self.assertTrue(self.sp.bot_name_matches({"user": "hermes-alice"}, "alice"))
        self.assertTrue(self.sp.bot_name_matches({"user": "Hermes_alice"}, "alice"))
        self.assertFalse(self.sp.bot_name_matches({"user": "hermes-bob"}, "alice"))
        self.assertFalse(self.sp.bot_name_matches({}, "alice"))

    def test_seen_markers(self):
        log = ("INFO slack-namespace: /hermes-alice -> /hermes handler registered\n"
               "INFO Slack connected as Hermes-alice\n")
        self.assertEqual(self.sp.seen_markers(log, "alice"), {"slash handler", "slack connected"})
        self.assertEqual(self.sp.seen_markers(log, "bob"), {"slack connected"})


if __name__ == "__main__":
    unittest.main()
