"""Stdlib tests: python -m unittest discover -s tests
Hermes-dependent checks (adapter round-trip) run only when HERMES_AGENT_DIR points at a Hermes checkout."""
import asyncio
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent.parent


def load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ns = load("plugins/slack-namespace/__init__.py", "slack_namespace")
fa = load("plugins/fallback-alert/__init__.py", "fallback_alert")
mk = load("scripts/make_manifest.py", "make_manifest")
inst = load("scripts/install.py", "install")


class SlackNamespace(unittest.TestCase):
    def test_umbrella(self):
        self.assertEqual(ns.umbrella_from_env({"HERMES_SLACK_SLASH": "hermes-alice"}), "/hermes-alice")
        self.assertEqual(ns.umbrella_from_env({"HERMES_SLACK_SLASH": "/hermes-alice "}), "/hermes-alice")
        self.assertIsNone(ns.umbrella_from_env({}))

    def test_to_builtin_keeps_payload(self):
        out = ns.to_builtin({"command": "/hermes-alice", "text": "new", "user_id": "U1"})
        self.assertEqual(out, {"command": "/hermes", "text": "new", "user_id": "U1"})

    def test_factory_acks_then_delegates(self):
        reg, got, acks = {}, {}, []

        class App:
            def command(self, name):
                def deco(f):
                    reg[name] = f
                    return f
                return deco

        class Adapter:
            async def _handle_slash_command(self, c):
                got["c"] = c

        async def ack(**kw):
            acks.append(kw)

        os.environ["HERMES_SLACK_SLASH"] = "hermes-alice"
        try:
            ns._slack_factory(App(), Adapter())
            asyncio.run(reg["/hermes-alice"](ack, {"command": "/hermes-alice", "text": "new"}))
        finally:
            del os.environ["HERMES_SLACK_SLASH"]
        self.assertEqual(acks[0]["response_type"], "ephemeral")
        self.assertEqual(got["c"]["command"], "/hermes")

    def test_factory_noop_without_env(self):
        reg = {}
        App = type("App", (), {"command": lambda self, n: (lambda f: reg.setdefault(n, f))})
        os.environ.pop("HERMES_SLACK_SLASH", None)
        ns._slack_factory(App(), None)
        self.assertEqual(reg, {})

    @unittest.skipUnless(os.environ.get("HERMES_AGENT_DIR"), "needs a Hermes checkout")
    def test_adapter_subcommand_mapping(self):
        sys.path.insert(0, os.environ["HERMES_AGENT_DIR"])
        from plugins.platforms.slack.adapter import SlackAdapter
        text = lambda t: SlackAdapter._slash_command_text(ns.to_builtin({"command": "/hermes-alice", "text": t}))
        self.assertEqual(text("new"), "/new")
        self.assertEqual(text("model x"), "/model x")
        self.assertEqual(text("hello there"), "hello there")
        self.assertEqual(text(""), "/help")


class FallbackAlert(unittest.TestCase):
    def setUp(self):
        fa._last_provider.clear()
        fa._last_account.clear()

    def test_decide(self):
        P = "openai-codex"
        self.assertIsNone(fa.decide(None, P, P))
        self.assertEqual(fa.decide(None, "anthropic", P), "fallback")
        self.assertEqual(fa.decide(P, "anthropic", P), "fallback")
        self.assertIsNone(fa.decide("anthropic", "anthropic", P))
        self.assertEqual(fa.decide("anthropic", P, P), "recover")

    def test_active_account(self):
        E = lambda *st: [{"label": f"a{i}", "priority": i, "last_status": s} for i, s in enumerate(st)]
        self.assertEqual(fa.active_account(E("ok", None)), "a0")
        self.assertEqual(fa.active_account(E("exhausted", "ok")), "a1")
        self.assertEqual(fa.active_account(E("exhausted", "dead")), "")
        self.assertIsNone(fa.active_account(E("ok")))

    def test_parse_account_names(self):
        self.assertEqual(fa.parse_account_names("p=Personal, w=Work,bad"), {"p": "Personal", "w": "Work"})

    def test_sequence_alerts_once_per_change(self):
        sent = []
        fa._send = sent.append
        fa._primary_provider = lambda: "openai-codex"
        E = lambda *st: [{"label": f"a{i}", "priority": i, "last_status": s} for i, s in enumerate(st)]
        pool = {"anthropic": E("ok", None)}
        fa._pool_entries = lambda p: pool.get(p, [])
        call = lambda sid, plat, prov: fa._on_post_api_request(session_id=sid, platform=plat, model="m", provider=prov)
        call("s1", "cli", "openai-codex")
        call("s1", "cli", "anthropic")
        call("s1", "cli", "anthropic")
        pool["anthropic"] = E("exhausted", "ok")
        call("s2", "slack", "anthropic")
        call("s2", "slack", "anthropic")
        call("s1", "cli", "openai-codex")
        kinds = [s.split("*")[1] for s in sent]
        self.assertEqual(kinds, ["Hermes model fallback", "Hermes account switch", "Hermes back on primary"])


class Manifest(unittest.TestCase):
    BASE = {
        "display_information": {"name": "Hermes"},
        "features": {"bot_user": {"display_name": "Hermes"},
                     "slash_commands": [{"command": "/hermes", "url": "https://x/slack"}, {"command": "/new"}]},
        "oauth_config": {"scopes": {"bot": ["chat:write", "commands"]}},
    }

    def test_namespace(self):
        m = mk.namespace(self.BASE, "alice")
        self.assertEqual(m["display_information"]["name"], "Hermes-alice")
        self.assertEqual(m["features"]["bot_user"]["display_name"], "Hermes-alice")
        self.assertEqual([c["command"] for c in m["features"]["slash_commands"]], ["/hermes-alice"])
        self.assertEqual(m["features"]["slash_commands"][0]["url"], "https://x/slack")
        self.assertIn("commands", m["oauth_config"]["scopes"]["bot"])
        self.assertEqual(self.BASE["display_information"]["name"], "Hermes")  # input untouched

    def test_bad_id(self):
        for bad in ["", "Alice", "a b", "x" * 30, "-a"]:
            with self.assertRaises(ValueError):
                mk.namespace(self.BASE, bad)

    def test_description_short_for_any_id(self):
        for ident in ["a", "x" * 21]:
            cmd = mk.namespace(self.BASE, ident)["features"]["slash_commands"][0]
            self.assertLessEqual(len(cmd["description"]), 75)
            self.assertLessEqual(len(cmd["command"]), 32)


class AlertDelivery(unittest.TestCase):
    def test_post_survives_one_shot_exit(self):
        """A one-shot process exiting right after the hook must still deliver the alert."""
        import subprocess
        import textwrap
        code = textwrap.dedent(f"""
            import importlib.util, time
            spec = importlib.util.spec_from_file_location("fa", {str(ROOT / "plugins/fallback-alert/__init__.py")!r})
            fa = importlib.util.module_from_spec(spec); spec.loader.exec_module(fa)
            def slow_post(text):
                time.sleep(0.5)
                print("DELIVERED", flush=True)
            fa._post = slow_post
            fa._send("x")
        """)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
        self.assertIn("DELIVERED", out.stdout)


class Install(unittest.TestCase):
    def test_set_env_upserts(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("A=1\nHERMES_SLACK_SLASH=old\n# c\n", encoding="utf-8")
            inst.set_env(p, "HERMES_SLACK_SLASH", "hermes-alice")
            inst.set_env(p, "NEW", "x")
            self.assertEqual(p.read_text(encoding="utf-8"), "A=1\nHERMES_SLACK_SLASH=hermes-alice\n# c\nNEW=x\n")


if __name__ == "__main__":
    unittest.main()
