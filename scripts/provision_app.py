#!/usr/bin/env python3
"""Admin tool: create and maintain teammates' Hermes-<id> Slack apps from one machine.

The admin owns every app, so the teammate never touches api.slack.com except to copy two tokens.

    python provision_app.py token set            # paste an app configuration *refresh* token once
    python provision_app.py token check          # rotate now and confirm it still works
    python provision_app.py create <id> --user U…  # create Hermes-<id>, print the remaining clicks
    python provision_app.py list                 # apps this machine created
    python provision_app.py update-all [--dry-run]  # re-apply the kit manifest to every app

App configuration tokens expire after 12 hours, but each rotation also returns a new refresh
token, so the stored refresh token keeps working for as long as it is rotated. Every run rotates
first and stores the new refresh token before using the access token. If Slack ever answers
`invalid_refresh_token`, generate a new one at https://api.slack.com/apps (bottom of the page,
"Your App Configuration Tokens") and run `token set` again.

The refresh token lives in the macOS Keychain (service hermes-slackbot-config-token) or, on other
systems, in a 0600 file next to the registry. The registry (id -> app id, owner member id) is
~/.config/hermes-slackbot/apps.json — kept outside the repo because it holds workspace IDs.
Needs `hermes` on PATH (the manifest comes from make_manifest.py). Stdlib only.
"""
import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_manifest  # noqa: E402

CONF = Path(os.environ.get("HERMES_SLACKBOT_CONF") or Path.home() / ".config" / "hermes-slackbot")
REGISTRY = CONF / "apps.json"
TOKEN_FILE = CONF / "config-refresh-token"
KEYCHAIN = ("hermes-slackbot-config-token", "refresh")
API = "https://slack.com/api/"


# ── refresh-token storage ─────────────────────────────────────────────────────

def _use_keychain() -> bool:
    return sys.platform == "darwin" and shutil.which("security") is not None and "HERMES_SLACKBOT_CONF" not in os.environ


def load_refresh() -> str:
    if _use_keychain():
        r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN[0], "-a", KEYCHAIN[1], "-w"],
                           capture_output=True, text=True)
        val = r.stdout.strip() if r.returncode == 0 else ""
    else:
        val = TOKEN_FILE.read_text(encoding="utf-8").strip() if TOKEN_FILE.exists() else ""
    if not val:
        sys.exit("No refresh token stored. Run:  python provision_app.py token set")
    return val


def save_refresh(value: str) -> None:
    if _use_keychain():
        r = subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN[0], "-a", KEYCHAIN[1], "-w", value],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"Could not write the Keychain item: {r.stderr.strip()}")
        return
    CONF.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value + "\n")
    os.replace(tmp, TOKEN_FILE)


# ── Slack Web API ─────────────────────────────────────────────────────────────

def call(method: str, retries: int = 5, **params) -> dict:
    """POST a Web API method; on HTTP 429 wait Slack's Retry-After and try again."""
    data = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode()
    for attempt in range(retries + 1):
        req = urllib.request.Request(API + method, data=data,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == retries:
                raise
            wait = int(e.headers.get("Retry-After") or 30)
            print(f"  rate limited by Slack on {method}; waiting {wait}s", file=sys.stderr)
            time.sleep(wait)


def access_token() -> str:
    """Rotate the refresh token; persist the new one *before* returning the access token."""
    res = call("tooling.tokens.rotate", refresh_token=load_refresh())
    if not res.get("ok"):
        sys.exit(f"tooling.tokens.rotate failed: {res.get('error')} — issue a new refresh token and run `token set`.")
    save_refresh(res["refresh_token"])
    return res["token"]


def check(res: dict, what: str) -> dict:
    if not res.get("ok"):
        detail = "".join(f"\n  {e.get('pointer', '')}: {e.get('message', '')}" for e in res.get("errors") or [])
        sys.exit(f"{what} failed: {res.get('error')}{detail}")
    return res


# ── registry ──────────────────────────────────────────────────────────────────

def load_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else {}


def save_registry(reg: dict) -> None:
    CONF.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def kit_manifest(ident: str) -> dict:
    desc = f"Personal Hermes agent ({ident}) — only its owner can use it"
    return make_manifest.namespace(make_manifest.hermes_manifest(f"Hermes-{ident}", desc), ident)


def setup_line(ident: str, user: str) -> str:
    """The one PowerShell line the teammate runs (see docs/admin-provision.ko.md). (pure — for tests)"""
    return (
        "$ProgressPreference='SilentlyContinue'; $k=\"$HOME\\hermes-slackbot\"; "
        "if (Test-Path \"$k\\.git\") { git -C $k pull -q } else { "
        "Invoke-WebRequest https://github.com/z0nam/hermes-slackbot/archive/refs/heads/main.zip -OutFile \"$env:TEMP\\hsb.zip\"; "
        "Remove-Item -Recurse -Force $k -ErrorAction SilentlyContinue; "
        "Expand-Archive -Force \"$env:TEMP\\hsb.zip\" $HOME; Rename-Item \"$HOME\\hermes-slackbot-main\" hermes-slackbot }; "
        f"python \"$k\\scripts\\setup_pc.py\" {ident} --user {user}"
    )


def links(app_id: str) -> list:
    base = f"https://api.slack.com/apps/{app_id}"
    return [
        ("1. Install to Workspace (as admin)", f"{base}/install-on-team"),
        ("2. App-Level Token: Generate, scope connections:write", f"{base}/general"),
        ("3. Collaborators: add the owner so they can copy the two tokens", f"{base}/collaborators"),
        ("Owner copies the bot token (xoxb-) here", f"{base}/oauth"),
        ("Owner copies the app-level token (xapp-) here", f"{base}/general"),
    ]


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_token(a) -> None:
    if a.action == "set":
        val = getpass.getpass("App configuration refresh token (xoxe-…, input hidden): ").strip()
        if not val.startswith("xoxe-"):
            sys.exit("That is not a refresh token (expected xoxe-…). Use the *Refresh Token*, not the access token.")
        save_refresh(val)
    res = call("tooling.tokens.rotate", refresh_token=load_refresh())
    if not res.get("ok"):
        sys.exit(f"Refresh token rejected: {res.get('error')}")
    save_refresh(res["refresh_token"])
    print(f"ok — config token works (team {res.get('team_id')}, user {res.get('user_id')}); new refresh token stored")


def cmd_create(a) -> None:
    ident = a.id.strip().lower()
    reg = load_registry()
    if ident in reg and not a.force:
        sys.exit(f"Hermes-{ident} is already registered as {reg[ident]['app_id']}. Use update-all, or --force.")
    if not a.user.startswith("U"):
        sys.exit("--user must be the owner's Slack member ID (U…).")
    try:
        manifest = json.dumps(kit_manifest(ident), ensure_ascii=False)
    except ValueError as e:
        sys.exit(str(e))
    tok = access_token()
    check(call("apps.manifest.validate", token=tok, manifest=manifest), "apps.manifest.validate")
    res = check(call("apps.manifest.create", token=tok, manifest=manifest), "apps.manifest.create")
    app_id = res["app_id"]  # credentials (client/signing secrets) are not needed for Socket Mode; not stored
    reg[ident] = {"app_id": app_id, "user": a.user, "created": time.strftime("%Y-%m-%d")}
    save_registry(reg)
    print(f"created Hermes-{ident}  ({app_id})\n\nRemaining clicks (about 2 minutes), then the owner's copy pages:")
    for label, url in links(app_id):
        print(f"  {label}\n    {url}")
    print(f"\nOn the teammate's PC (PowerShell), when the two tokens are ready:\n  {setup_line(ident, a.user)}")


def cmd_list(a) -> None:
    reg = load_registry()
    if not reg:
        print("(no apps registered on this machine)")
    for ident, row in sorted(reg.items()):
        print(f"Hermes-{ident:<12} {row['app_id']}  owner {row['user']}  created {row['created']}")


def changed_paths(old, new, path="") -> list:
    """Top-level-ish diff for --dry-run. (pure — for tests)"""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for k in sorted(set(old) | set(new)):
            out += changed_paths(old.get(k), new.get(k), f"{path}/{k}")
        return out
    return [] if old == new else [path or "/"]


def cmd_update_all(a) -> None:
    reg = load_registry()
    if not reg:
        sys.exit("No apps registered on this machine.")
    tok = access_token()
    for ident, row in sorted(reg.items()):
        new = kit_manifest(ident)
        if a.dry_run:
            cur = check(call("apps.manifest.export", token=tok, app_id=row["app_id"]), f"export {ident}")["manifest"]
            diff = changed_paths(cur, new)
            print(f"Hermes-{ident}: " + (", ".join(diff) if diff else "no change"))
            continue
        res = check(call("apps.manifest.update", token=tok, app_id=row["app_id"],
                         manifest=json.dumps(new, ensure_ascii=False)), f"update {ident}")
        note = "  → scopes changed: reinstall at " + links(row["app_id"])[0][1] if res.get("permissions_updated") else ""
        print(f"Hermes-{ident}: updated{note}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("token", help="store or check the app configuration refresh token")
    t.add_argument("action", choices=["set", "check"])
    c = sub.add_parser("create", help="create Hermes-<id> from the kit manifest")
    c.add_argument("id")
    c.add_argument("--user", required=True, help="owner's Slack member ID (U…)")
    c.add_argument("--force", action="store_true", help="create again even if the id is registered")
    sub.add_parser("list", help="apps created from this machine")
    u = sub.add_parser("update-all", help="re-apply the kit manifest to every registered app")
    u.add_argument("--dry-run", action="store_true", help="show what would change, update nothing")
    a = ap.parse_args()
    {"token": cmd_token, "create": cmd_create, "list": cmd_list, "update-all": cmd_update_all}[a.cmd](a)


if __name__ == "__main__":
    main()
