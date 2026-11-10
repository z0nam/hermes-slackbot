#!/usr/bin/env python3
"""Generate a Slack app manifest for a personal Hermes bot that won't collide with others.

Starts from Hermes' own manifest (`hermes slack manifest --agent-view`, so scopes and events stay
in sync with your Hermes version) and changes only:
  * app name + bot display name  -> "Hermes-<id>"
  * slash commands               -> just "/hermes-<id>"  (needs the slack-namespace plugin)
  * bot scopes                   -> + groups:write, chat:write.customize  (KIT_BOT_SCOPES)
  * KIT_USER_SCOPES are NOT on member apps: members' user tokens come from one shared OAuth app
    (oauth_app_manifest, created once by `provision_app.py create-oauth-app`)

Usage:
    python make_manifest.py <id> [--out PATH] [--description TEXT]
    python make_manifest.py alice --out slack-manifest.json

Paste the output into https://api.slack.com/apps -> Create New App -> From a manifest
(or, for an existing app: Features -> App Manifest -> Edit), then Save.
Stdlib only; works on Windows, macOS and Linux.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,20}$")  # Slack: lowercase, max 32 chars incl. "/hermes-"

# Bot scopes the kit needs on top of Hermes' own manifest:
#   groups:write         create the owner's private "hermes-<id>" channel (conversations.create
#                        is_private) and invite the owner (conversations.invite)
#   chat:write.customize slack-model-display sets the per-post username "Hermes-<id> (<model>)"
KIT_BOT_SCOPES = ["groups:write", "chat:write.customize"]

# User-token scopes the OWNER grants for themselves (jaix OAuth, never the admin on their behalf), so
# slack-tools can read their DMs/private channels, search, and handle files. Writes still ask per call.
KIT_USER_SCOPES = [
    "identify", "search:read",
    "channels:history", "groups:history", "im:history", "mpim:history",
    "channels:read", "groups:read", "im:read", "mpim:read", "users:read",
    "files:read", "files:write", "chat:write", "im:write",
]
# User scopes of the shared OAuth app (one app for everyone's own user token; slack-tools uses it).
# Where Slack sends the member back after "Allow" (the jaix share server exchanges the code).
OAUTH_REDIRECT_URL = os.environ.get("HERMES_SLACKBOT_OAUTH_REDIRECT",
                                    "https://jaix.namun.net/slack/oauth/callback")


def hermes_manifest(name: str, description: str) -> dict:
    exe = shutil.which("hermes")
    if not exe:
        sys.exit("hermes not found on PATH — install Hermes Agent first.")
    out = subprocess.run(
        [exe, "slack", "manifest", "--agent-view", "--name", name, "--description", description],
        capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        sys.exit(f"`hermes slack manifest` failed:\n{out.stderr}")
    return json.loads(out.stdout)


def namespace(manifest: dict, ident: str) -> dict:
    """Apply the per-user name and single namespaced command. (pure — for tests)"""
    if not ID_RE.match(ident):
        raise ValueError(f"id {ident!r}: use 1-21 chars of a-z, 0-9, '-', '_' (lowercase, start with a letter/digit)")
    m = json.loads(json.dumps(manifest))
    name = f"Hermes-{ident}"
    m.setdefault("display_information", {})["name"] = name
    feats = m.setdefault("features", {})
    feats.setdefault("bot_user", {})["display_name"] = name
    old = feats.get("slash_commands") or [{}]
    url = next((c.get("url") for c in old if c.get("url")), "https://hermes-agent.local/slack/commands")
    feats["slash_commands"] = [{
        "command": f"/hermes-{ident}",
        # Fixed text, independent of the id length (Slack caps slash-command descriptions).
        "description": "Subcommand (new, stop, model, help …) or a question",
        "usage_hint": "[subcommand] [args] | question",
        "should_escape": False,
        "url": url,
    }]
    return m


def with_kit_scopes(manifest: dict) -> dict:
    """Add KIT_BOT_SCOPES, keeping existing entries. (pure)"""
    m = json.loads(json.dumps(manifest))
    scopes = m.setdefault("oauth_config", {}).setdefault("scopes", {}).setdefault("bot", [])
    scopes.extend(s for s in KIT_BOT_SCOPES if s not in scopes)
    return m


OAUTH_APP_NAME = "JAIX Slack 연결"


def oauth_app_manifest(name: str = OAUTH_APP_NAME) -> dict:
    """The one shared app members authorize to give their own Hermes a user token: user scopes and the
    jaix callback only — no bot, no events, no Socket Mode. (pure — for tests)"""
    return {
        "_metadata": {"major_version": 1, "minor_version": 1},
        "display_information": {
            "name": name,
            "description": "Connects your own Slack account to your Hermes (DMs, private channels, files)",
        },
        "oauth_config": {"redirect_urls": [OAUTH_REDIRECT_URL], "scopes": {"user": list(KIT_USER_SCOPES)}},
        "settings": {"org_deploy_enabled": False, "socket_mode_enabled": False, "token_rotation_enabled": False},
    }


def kit_manifest(manifest: dict, ident: str) -> dict:
    """Everything the kit changes in Hermes' manifest: names, one command, extra scopes."""
    return with_kit_scopes(namespace(manifest, ident))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("id", help="short personal id, e.g. your Slack handle (lowercase)")
    ap.add_argument("--out", help="write to this file instead of stdout")
    ap.add_argument("--description", default=None, help="app description (default: personal Hermes agent)")
    a = ap.parse_args()
    ident = a.id.strip().lower()
    desc = a.description or f"Personal Hermes agent ({ident}) — only its owner can use it"
    m = kit_manifest(hermes_manifest(f"Hermes-{ident}", desc), ident)
    text = json.dumps(m, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"wrote {a.out}  (app: Hermes-{ident}, command: /hermes-{ident})", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
