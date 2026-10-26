#!/usr/bin/env python3
"""Teammate PC, one command: connect this Hermes to the Hermes-<id> app the admin already created.

    python setup_pc.py <id> --user U…        # asks for the two tokens (input hidden)

Steps: check both tokens against Slack (the bot token must belong to Hermes-<id>), write
SLACK_BOT_TOKEN / SLACK_APP_TOKEN / SLACK_ALLOWED_USERS to the Hermes .env, install the kit
plugins (install.py), register and restart the gateway, then wait for the gateway log to show
the slash handler and the Slack connection. Token values are never printed.
See docs/admin-provision.ko.md for the admin side. Stdlib only; written for Windows PowerShell.
"""
import argparse
import getpass
import json
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import install  # noqa: E402
import make_manifest  # noqa: E402

API = "https://slack.com/api/"
WAIT_SECONDS = 120


def slack(method: str, token: str) -> dict:
    req = urllib.request.Request(API + method, data=b"",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def ask_token(label: str, prefix: str) -> str:
    for _ in range(3):
        val = getpass.getpass(f"{label} ({prefix}…, paste then Enter; input is hidden): ").strip()
        if val.startswith(prefix):
            return val
        print(f"  that does not start with {prefix} — try again")
    sys.exit("giving up: token not entered")


def bot_name_matches(auth: dict, ident: str) -> bool:
    """auth.test 'user' is the bot user's handle; compare loosely. (pure — for tests)"""
    return (auth.get("user") or "").lower().replace("_", "-") == f"hermes-{ident}"


def markers(ident: str) -> dict:
    return {
        "slash handler": f"slack-namespace: /hermes-{ident} -> /hermes handler registered",
        "slack connected": "slack connected",
    }


def seen_markers(text: str, ident: str) -> set:
    """Which gateway.log markers appear in text. (pure — for tests)"""
    return {name for name, needle in markers(ident).items() if needle.lower() in text.lower()}


def wait_for_log(log: Path, offset: int, ident: str) -> set:
    found, deadline = set(), time.time() + WAIT_SECONDS
    while time.time() < deadline and found != set(markers(ident)):
        if log.exists():
            with open(log, "rb") as f:
                f.seek(offset if log.stat().st_size >= offset else 0)
                found |= seen_markers(f.read().decode("utf-8", "replace"), ident)
        time.sleep(3)
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("id", help="the id the admin used, e.g. alice  (app Hermes-alice)")
    ap.add_argument("--user", required=True, help="owner's Slack member ID (U…); the only allowed user")
    ap.add_argument("--home-channel", help="optional SLACK_HOME_CHANNEL (C…/D…) for alerts")
    ap.add_argument("--no-restart", action="store_true", help="write settings only; don't touch the gateway")
    a = ap.parse_args()
    ident = a.id.strip().lower()
    if not make_manifest.ID_RE.match(ident):
        sys.exit(f"bad id {ident!r}: use the same id the admin gave you")
    if not a.user.startswith("U"):
        sys.exit("--user must be a Slack member ID starting with U")

    env_path = Path(install.run("config", "env-path"))
    print(f"Hermes settings: {env_path}")
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    if any(line.split("=", 1)[0].strip() == "SLACK_BOT_TOKEN" for line in existing.splitlines()):
        if input("A Slack bot token is already set. Replace it? [y/N] ").strip().lower() != "y":
            sys.exit("stopped; nothing changed")

    bot = ask_token("Bot User OAuth Token", "xoxb-")
    try:
        auth = slack("auth.test", bot)
    except OSError as e:
        sys.exit(f"could not reach Slack to check the token: {e}")
    if not auth.get("ok"):
        sys.exit(f"bot token rejected by Slack: {auth.get('error')}")
    if not bot_name_matches(auth, ident):
        print(f"  warning: this token belongs to bot '{auth.get('user')}', not Hermes-{ident}")
        if input("  continue anyway? [y/N] ").strip().lower() != "y":
            sys.exit("stopped; nothing changed")
    print(f"  ok: bot {auth.get('user')} in workspace {auth.get('team')}")

    app = ask_token("App-Level Token", "xapp-")
    try:
        conn = slack("apps.connections.open", app)
    except OSError as e:
        sys.exit(f"could not reach Slack to check the token: {e}")
    if not conn.get("ok"):
        sys.exit(f"app-level token rejected by Slack: {conn.get('error')} (it needs the connections:write scope)")
    print("  ok: app-level token can open Socket Mode")

    install.set_env(env_path, "SLACK_BOT_TOKEN", bot)
    install.set_env(env_path, "SLACK_APP_TOKEN", app)
    install.set_env(env_path, "SLACK_ALLOWED_USERS", a.user)
    if a.home_channel:
        install.set_env(env_path, "SLACK_HOME_CHANNEL", a.home_channel)
    print("  wrote SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_ALLOWED_USERS" + (", SLACK_HOME_CHANNEL" if a.home_channel else ""))

    r = subprocess.run([sys.executable, str(HERE / "install.py"), ident])
    if r.returncode != 0:
        sys.exit("install.py failed (see above)")
    if a.no_restart:
        print("\nSettings written. Run  hermes gateway install  and  hermes gateway restart  when ready.")
        return

    log = env_path.parent / "logs" / "gateway.log"
    offset = log.stat().st_size if log.exists() else 0
    install_out = subprocess.run([shutil.which("hermes"), "gateway", "install"],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace")
    if install_out.returncode != 0:
        print(f"  note: `hermes gateway install` returned {install_out.returncode}:\n{install_out.stderr or install_out.stdout}")
    install.run("gateway", "restart")
    print(f"  gateway restarted; waiting up to {WAIT_SECONDS}s for {log.name} …")
    found = wait_for_log(log, offset, ident)
    for name in markers(ident):
        print(f"  {'ok ' if name in found else 'MISSING'}  {name}")
    if found != set(markers(ident)):
        sys.exit("\nNot connected yet. Check  hermes gateway status  and the end of gateway.log.")
    print(f"\nDone. In Slack: DM Hermes-{ident} 'hi', then type  /hermes-{ident} help")


if __name__ == "__main__":
    main()
