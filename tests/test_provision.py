"""Stdlib tests for the admin provisioning flow (scripts/provision_app.py, scripts/setup_pc.py).
No network: Slack calls are replaced with fakes."""
import importlib.util
import json
import os
import sys
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

    def test_create_oauth_app_stores_credentials_0600(self):
        self.pa.save_refresh("xoxe-1")
        manifests = []

        def fake(method, **p):
            if method == "tooling.tokens.rotate":
                return {"ok": True, "token": "t", "refresh_token": "xoxe-2"}
            if method == "apps.manifest.create":
                manifests.append(json.loads(p["manifest"]))
                return {"ok": True, "app_id": "A7", "credentials": {"client_id": "1.2", "client_secret": "SECRET-xyz",
                                                                     "signing_secret": "SIGN-abc"}}
            return {"ok": True}
        with mock.patch.object(self.pa, "call", fake), mock.patch("builtins.print"):
            self.pa.cmd_create_oauth_app(NS(name="JAIX Slack 연결", force=False))
            with self.assertRaises(SystemExit):          # once only, unless --force
                self.pa.cmd_create_oauth_app(NS(name="JAIX Slack 연결", force=False))
        self.assertEqual(manifests[0]["display_information"]["name"], "JAIX Slack 연결")
        self.assertIn("im:history", manifests[0]["oauth_config"]["scopes"]["user"])
        f = Path(self.tmp.name, "slack-apps.json")
        self.assertEqual(self.pa.APP_SECRETS, f)        # test conf keeps the real path untouched
        self.assertEqual(json.loads(f.read_text()), {"app_id": "A7", "client_id": "1.2", "client_secret": "SECRET-xyz"})
        self.assertEqual(oct(f.stat().st_mode & 0o777), "0o600")
        self.assertEqual(self.pa.load_registry(), {})    # not a Hermes app: update-all must never touch it
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ["config-refresh-token", "slack-apps.json"])

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

    EXPORTED = {
        "display_information": {"name": "Hermes-alice", "description": "Personal Hermes agent (alice) — only its owner can use it"},
        "features": {"bot_user": {"display_name": "Hermes-alice"},
                     "slash_commands": [{"command": "/hermes-alice", "url": "https://x/slack"}]},
        "oauth_config": {"scopes": {"bot": ["chat:write", "commands"]}},
        "settings": {"socket_mode_enabled": True},
    }

    def test_rename_manifest_changes_only_names(self):
        m = self.pa.rename_manifest(self.EXPORTED, "alice", "al")
        self.assertEqual(m["display_information"]["name"], "Hermes-al")
        self.assertIn("(al)", m["display_information"]["description"])
        self.assertEqual(m["features"]["bot_user"]["display_name"], "Hermes-al")
        self.assertEqual([c["command"] for c in m["features"]["slash_commands"]], ["/hermes-al"])
        self.assertEqual(m["features"]["slash_commands"][0]["url"], "https://x/slack")
        self.assertEqual(m["oauth_config"], self.EXPORTED["oauth_config"])  # scopes untouched -> no reinstall
        self.assertEqual(m["settings"], self.EXPORTED["settings"])
        self.assertEqual(self.EXPORTED["display_information"]["name"], "Hermes-alice")  # input untouched

    def _rename(self, dry_run=False, old="alice", new="al"):
        self.pa.save_refresh("xoxe-1")
        self.pa.save_registry({"alice": {"app_id": "A1", "user": "U1", "created": "2026-11-05"},
                               "bob": {"app_id": "A2", "user": "U2", "created": "2026-11-05"}})
        calls = []

        def fake(method, **p):
            calls.append((method, p.get("app_id")))
            if method == "tooling.tokens.rotate":
                return {"ok": True, "token": "t", "refresh_token": "xoxe-2"}
            if method == "apps.manifest.export":
                return {"ok": True, "manifest": self.EXPORTED}
            if method == "apps.manifest.update":
                self.assertEqual(json.loads(p["manifest"])["features"]["slash_commands"][0]["command"], "/hermes-al")
                return {"ok": True, "app_id": p["app_id"], "permissions_updated": False}
            return {"ok": True}

        with mock.patch.object(self.pa, "call", fake), mock.patch("builtins.print"):
            self.pa.cmd_rename(NS(old=old, new=new, dry_run=dry_run))
        return calls

    def test_rename_updates_app_and_moves_registry_key(self):
        calls = self._rename()
        self.assertEqual([c[0] for c in calls], ["tooling.tokens.rotate", "apps.manifest.export", "apps.manifest.update"])
        self.assertEqual(calls[-1][1], "A1")
        reg = self.pa.load_registry()
        self.assertNotIn("alice", reg)
        self.assertEqual((reg["al"]["app_id"], reg["al"]["user"], reg["al"]["renamed_from"]), ("A1", "U1", "alice"))

    def test_rename_dry_run_changes_nothing(self):
        calls = self._rename(dry_run=True)
        self.assertNotIn("apps.manifest.update", [c[0] for c in calls])
        self.assertIn("alice", self.pa.load_registry())

    def test_rename_refuses_unknown_taken_or_bad_ids(self):
        for old, new in [("nobody", "x"), ("alice", "bob"), ("alice", "Bad Id")]:
            with self.assertRaises(SystemExit):
                self._rename(old=old, new=new)
            self.assertIn("alice", self.pa.load_registry())

    def test_kit_changes_hides_server_defaults_and_spells_out_scopes(self):
        cur = {"oauth_config": {"scopes": {"bot": ["chat:write", "commands"]}, "pkce_enabled": False},
               "settings": {"is_mcp_enabled": False}, "display_information": {"name": "Hermes-a"}}
        new = {"_metadata": {"major_version": 1}, "display_information": {"name": "Hermes-a"},
               "oauth_config": {"scopes": {"bot": ["commands", "chat:write", "groups:write"]}}}
        self.assertEqual(self.pa.kit_changes(cur, new), ["/oauth_config/scopes/bot (+groups:write)"])
        new["oauth_config"]["scopes"]["bot"] = ["commands", "chat:write"]  # order only
        self.assertEqual(self.pa.kit_changes(cur, new), [])
        new["display_information"]["name"] = "Hermes-b"
        self.assertEqual(self.pa.kit_changes(cur, new), ["/display_information/name"])

    def test_update_all_continues_past_an_unreachable_app(self):
        self.pa.save_refresh("xoxe-1")
        self.pa.save_registry({"alice": {"app_id": "A1"}, "bob": {"app_id": "A2"}, "carol": {"app_id": "A3"}})
        updated = []

        def fake(method, **p):
            if method == "tooling.tokens.rotate":
                return {"ok": True, "token": "t", "refresh_token": "xoxe-2"}
            if method == "apps.manifest.update":
                if p["app_id"] == "A2":
                    return {"ok": False, "error": "no_permission"}
                updated.append(p["app_id"])
                return {"ok": True, "permissions_updated": True}
            return {"ok": True}

        with mock.patch.object(self.pa, "call", fake), mock.patch("builtins.print"), \
                mock.patch.object(self.pa, "kit_manifest", lambda ident: {"n": ident}):
            with self.assertRaises(SystemExit) as cm:
                self.pa.cmd_update_all(NS(dry_run=False))
        self.assertEqual(updated, ["A1", "A3"])
        self.assertIn("bob (no_permission)", str(cm.exception.code))

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
        self.assertTrue(self.sp.bot_name_matches({"user": "hermesalice"}, "alice"))  # Slack's real handle shape
        self.assertFalse(self.sp.bot_name_matches({"user": "hermesbob"}, "alice"))

    def test_seen_markers(self):
        log = ("INFO slack-namespace: /hermes-alice -> /hermes handler registered\n"
               "INFO Slack connected as Hermes-alice\n")
        self.assertEqual(self.sp.seen_markers(log, "alice"), {"slash handler", "slack connected"})
        self.assertEqual(self.sp.seen_markers(log, "bob"), {"slack connected"})

    def _fake_slack(self, replies):
        calls = []
        def fake(method, token, **params):
            calls.append((method, params))
            r = replies[method]
            return r.pop(0) if isinstance(r, list) else r
        return fake, calls

    def test_owner_channel_created_private_and_owner_invited(self):
        fake, calls = self._fake_slack({"conversations.create": {"ok": True, "channel": {"id": "GTEST0001"}},
                                        "conversations.invite": {"ok": True}})
        with mock.patch.object(self.sp, "slack", fake):
            msg = self.sp.ensure_owner_channel("xoxb-TEST-1", "alice", "UOWNER0001")
        self.assertTrue(msg.startswith("ok:"))
        self.assertNotIn("GTEST0001", msg)  # never print channel IDs
        self.assertEqual(calls[0], ("conversations.create", {"name": "hermes-alice", "is_private": "true"}))
        self.assertEqual(calls[1], ("conversations.invite", {"channel": "GTEST0001", "users": "UOWNER0001"}))

    def test_owner_channel_is_idempotent_when_name_taken(self):
        page1 = {"ok": True, "channels": [{"id": "GOTHER001", "name": "x"}],
                 "response_metadata": {"next_cursor": "c2"}}
        page2 = {"ok": True, "channels": [{"id": "GTEST0001", "name": "hermes-alice"}]}
        fake, calls = self._fake_slack({"conversations.create": {"ok": False, "error": "name_taken"},
                                        "conversations.list": [page1, page2],
                                        "conversations.invite": {"ok": False, "error": "already_in_channel"}})
        with mock.patch.object(self.sp, "slack", fake):
            msg = self.sp.ensure_owner_channel("xoxb-TEST-1", "alice", "UOWNER0001")
        self.assertTrue(msg.startswith("ok:"), msg)
        self.assertEqual(calls[2][1].get("cursor"), "c2")
        self.assertEqual(calls[-1], ("conversations.invite", {"channel": "GTEST0001", "users": "UOWNER0001"}))

    def test_owner_channel_skips_name_taken_by_a_channel_the_bot_is_not_in(self):
        fake, calls = self._fake_slack({"conversations.create": {"ok": False, "error": "name_taken"},
                                        "conversations.list": {"ok": True, "channels": []}})
        with mock.patch.object(self.sp, "slack", fake):
            msg = self.sp.ensure_owner_channel("xoxb-TEST-1", "alice", "UOWNER0001")
        self.assertTrue(msg.startswith("note:"))
        self.assertNotIn("conversations.invite", [c[0] for c in calls])

    def test_owner_channel_never_raises(self):
        fake, _ = self._fake_slack({"conversations.create": {"ok": False, "error": "missing_scope"}})
        with mock.patch.object(self.sp, "slack", fake):
            self.assertIn("missing_scope", self.sp.ensure_owner_channel("xoxb-TEST-1", "alice", "UOWNER0001"))
        with mock.patch.object(self.sp, "slack", side_effect=OSError("offline")):
            self.assertTrue(self.sp.ensure_owner_channel("xoxb-TEST-1", "alice", "UOWNER0001").startswith("note:"))

    # --- unattended (--secrets-file), used by jaix-setup ---------------------------------------
    def _secrets(self, d, **over):
        f = Path(d) / "s.json"
        f.write_text(json.dumps({"bot_token": "xoxb-TEST-1", "app_token": "xapp-TEST-1", **over}), encoding="utf-8")
        return f

    def test_read_secrets_deletes_file_even_when_bad(self):
        with tempfile.TemporaryDirectory() as d:
            f = self._secrets(d)
            self.assertEqual(self.sp.read_secrets(f), {"bot": "xoxb-TEST-1", "app": "xapp-TEST-1", "user": ""})
            self.assertFalse(f.exists())
            bad = self._secrets(d, app_token="nope")
            with self.assertRaises(SystemExit):
                self.sp.read_secrets(bad)
            self.assertFalse(bad.exists())

    def test_read_secrets_user_token_alone_or_with_bot(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "u.json"
            f.write_text(json.dumps({"user_token": "xoxp-TEST-9"}), encoding="utf-8")
            self.assertEqual(self.sp.read_secrets(f), {"bot": "", "app": "", "user": "xoxp-TEST-9"})
            self.assertEqual(self.sp.read_secrets(self._secrets(d, user_token="xoxp-TEST-9"))["user"], "xoxp-TEST-9")
            for bad in ({"user_token": "xoxb-TEST-9"}, {"bot_token": "xoxb-TEST-1", "user_token": "xoxp-TEST-9"}):
                f.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaises(SystemExit):
                    self.sp.read_secrets(f)
                self.assertFalse(f.exists())

    def test_slack_tools_settings_run_bundled_sapi_per_call(self):
        env = Path("/h/.env")
        got = dict(self.sp.slack_tools_settings(env, "/py/python", "example.slack.com"))
        pre = "plugins.entries.slack-tools.settings."
        self.assertEqual(json.loads(got[pre + "executable"]), ["/py/python", str(Path("/h/plugins/slack-tools/sapi.py"))])
        self.assertEqual(json.loads(got[pre + "workspace_hosts"]), ["example.slack.com"])
        self.assertEqual(got[pre + "approval_policy"], "per_call")
        self.assertEqual(got[pre + "download_dir"], str(Path("/h/cache/slack-files")))

    def test_enable_user_token_refuses_someone_elses_token(self):
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text("SLACK_BOT_TOKEN=xoxb-TEST-1\n", encoding="utf-8")
            auth = {"ok": True, "user_id": "UADMIN0001", "url": "https://example.slack.com/"}
            with mock.patch.object(self.sp, "slack", return_value=auth), \
                    mock.patch.object(self.sp.install, "run") as run, \
                    mock.patch.object(self.sp.subprocess, "run") as sub, self.assertRaises(SystemExit) as e:
                self.sp.enable_user_token(env, "xoxp-TEST-9", "UOWNER0001")
            self.assertIn("different Slack user", str(e.exception))
            self.assertNotIn("SLACK_USER_TOKEN", env.read_text(encoding="utf-8"))
            run.assert_not_called()
            sub.assert_not_called()

    def test_enable_user_token_stores_and_configures_for_owner(self):
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            auth = {"ok": True, "user_id": "UOWNER0001", "url": "https://example.slack.com/"}
            with mock.patch.object(self.sp, "slack", return_value=auth), \
                    mock.patch.object(self.sp.install, "run") as run, \
                    mock.patch.object(self.sp.subprocess, "run", return_value=mock.Mock(returncode=0)) as sub, \
                    mock.patch("builtins.print"):
                self.sp.enable_user_token(env, "xoxp-TEST-9", "UOWNER0001")
            self.assertIn("SLACK_USER_TOKEN=xoxp-TEST-9", env.read_text(encoding="utf-8"))
            self.assertIn("--tools-only", sub.call_args.args[0])
            keys = [c.args[2] for c in run.call_args_list if c.args[:2] == ("config", "set")]
            self.assertIn("plugins.entries.slack-tools.settings.approval_policy", keys)
            self.assertIn(mock.call("tools", "enable", "slack", "--platform", "slack"), run.call_args_list)
            for c in run.call_args_list + sub.call_args_list:  # the token never goes on a command line
                self.assertNotIn("xoxp-TEST-9", json.dumps([str(x) for x in c.args]))

    def test_user_token_only_requires_bot_already_owned_by_user(self):
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            for text in ("SLACK_BOT_TOKEN=xoxb-T\nSLACK_ALLOWED_USERS=UOTHER0001\n",
                         "SLACK_BOT_TOKEN=xoxb-T\nSLACK_ALLOWED_USERS=UOWNER0001,UOTHER0001\n",
                         "SLACK_ALLOWED_USERS=UOWNER0001\n"):
                env.write_text(text, encoding="utf-8")
                f = Path(d) / "u.json"
                f.write_text(json.dumps({"user_token": "xoxp-TEST-9"}), encoding="utf-8")
                argv = ["setup_pc.py", "alice", "--user", "UOWNER0001", "--secrets-file", str(f)]
                with mock.patch.object(self.sp.install, "run", return_value=str(env)), \
                        mock.patch.object(self.sp, "enable_user_token") as enable, \
                        mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"), \
                        self.assertRaises(SystemExit) as e:
                    self.sp.main()
                self.assertIn("not set up for --user alone", str(e.exception))
                enable.assert_not_called()
                self.assertFalse(f.exists())
            env.write_text("SLACK_BOT_TOKEN=xoxb-T\nSLACK_ALLOWED_USERS=UOWNER0001\n", encoding="utf-8")
            f.write_text(json.dumps({"user_token": "xoxp-TEST-9"}), encoding="utf-8")
            argv = ["setup_pc.py", "alice", "--user", "UOWNER0001", "--secrets-file", str(f), "--no-restart"]
            with mock.patch.object(self.sp.install, "run", return_value=str(env)), \
                    mock.patch.object(self.sp, "enable_user_token") as enable, \
                    mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
                self.sp.main()
            enable.assert_called_once_with(env, "xoxp-TEST-9", "UOWNER0001")

    def test_read_secrets_stops_when_delete_fails(self):
        with tempfile.TemporaryDirectory() as d:
            f = self._secrets(d)
            with mock.patch.object(Path, "unlink", side_effect=PermissionError("held")), \
                 self.assertRaises(SystemExit) as e:
                self.sp.read_secrets(f)
            self.assertIn("could not delete", str(e.exception))

    def test_dm_channel_none_when_slack_refuses(self):
        with mock.patch.object(self.sp, "slack", return_value={"ok": False, "error": "missing_scope"}):
            self.assertIsNone(self.sp.dm_channel("xoxb-TEST", "U1"))
        with mock.patch.object(self.sp, "slack", side_effect=OSError("down")):
            self.assertIsNone(self.sp.dm_channel("xoxb-TEST", "U1"))

    def test_backup_env_copies_before_change(self):
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            self.assertIsNone(self.sp.backup_env(env))
            env.write_text("A=1\n", encoding="utf-8")
            self.assertEqual(self.sp.backup_env(env).read_text(encoding="utf-8"), "A=1\n")

    def _run_main(self, d, argv, env_text="", gw_code=0):
        env = Path(d) / ".env"
        if env_text:
            env.write_text(env_text, encoding="utf-8")
        calls = []

        def fake_run(cmd, **kw):
            calls.append((cmd, kw))
            return NS(returncode=gw_code if "gateway" in cmd else 0, stdout="", stderr="boom")

        def fake_slack(method, token, **params):
            if method == "conversations.open":
                self.assertEqual(params, {"users": "U123"})
                return {"ok": True, "channel": {"id": "D0TEST"}}
            return {"ok": True, "user": "hermes-alice", "team": "T"}

        with mock.patch.object(self.sp.install, "run", side_effect=lambda *a: str(env) if a[:2] == ("config", "env-path") else ""), \
             mock.patch.object(self.sp, "slack", side_effect=fake_slack), \
             mock.patch.object(self.sp.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(self.sp.shutil, "which", return_value="hermes"), \
             mock.patch.object(self.sp, "wait_for_log", return_value=set(self.sp.markers("alice"))), \
             mock.patch("builtins.input", side_effect=AssertionError("asked")), \
             mock.patch.object(self.sp.getpass, "getpass", side_effect=AssertionError("asked")), \
             mock.patch.object(sys, "argv", ["setup_pc.py", "alice", "--user", "U123", *argv]):
            self.sp.main()
        return env, calls

    def test_unattended_never_asks_and_writes_env(self):
        with tempfile.TemporaryDirectory() as d:
            f = self._secrets(d)
            env, calls = self._run_main(d, ["--secrets-file", str(f)])
            text = env.read_text(encoding="utf-8")
            self.assertIn("SLACK_BOT_TOKEN=xoxb-TEST-1", text)
            self.assertIn("SLACK_ALLOWED_USERS=U123", text)
            self.assertIn("SLACK_HOME_CHANNEL=D0TEST", text)  # no "No home channel is set" notice on first chat
            self.assertFalse(f.exists())
            gw = [c for c in calls if "gateway" in c[0]][0]
            self.assertIn("--start-on-login", gw[0])
            self.assertIs(gw[1]["stdin"], self.sp.subprocess.DEVNULL)  # no UAC question -> Startup folder

    def test_unattended_keeps_existing_token_without_replace(self):
        with tempfile.TemporaryDirectory() as d:
            f = self._secrets(d)
            with self.assertRaises(SystemExit) as e:
                self._run_main(d, ["--secrets-file", str(f)], env_text="SLACK_BOT_TOKEN=xoxb-OLD\n")
            self.assertIn("--replace", str(e.exception))
            self.assertFalse(f.exists())
            env, _ = self._run_main(d, ["--secrets-file", str(self._secrets(d)), "--replace"],
                                    env_text="SLACK_BOT_TOKEN=xoxb-OLD\n")
            self.assertIn("xoxb-TEST-1", env.read_text(encoding="utf-8"))
            self.assertTrue(list(Path(d).glob(".env.bak-*")))

    def test_unattended_gateway_install_failure_is_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit) as e:
                self._run_main(d, ["--secrets-file", str(self._secrets(d))], gw_code=1)
            self.assertIn("gateway install", str(e.exception))


if __name__ == "__main__":
    unittest.main()
