#!/usr/bin/env python3
"""Install the kit's plugins into your Hermes and point HERMES_SLACK_SLASH at your command.

    python install.py <id>               # copy plugins, set HERMES_SLACK_SLASH=hermes-<id>, enable
    python install.py <id> --link        # symlink instead of copy (for kit developers)
    python install.py <id> --no-alert    # skip the fallback-alert plugin
    python install.py --forwarded-only   # install only forwarded-message support
    python install.py <id> --with-forwarded  # opt in during a full kit install

Resolves HERMES_HOME via `hermes config env-path`, so profiles and Windows paths
(%LOCALAPPDATA%\\hermes) work without hardcoding. Restart the gateway afterwards:
    hermes gateway restart
Stdlib only.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
PLUGINS = ["slack-namespace", "fallback-alert"]


def run(*args: str) -> str:
    exe = shutil.which("hermes")
    if not exe:
        sys.exit("hermes not found on PATH — install Hermes Agent first.")
    r = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        sys.exit(f"`hermes {' '.join(args)}` failed:\n{r.stderr or r.stdout}")
    return r.stdout.strip()


def set_env(env_path: Path, key: str, value: str) -> None:
    """Upsert KEY=value in a .env file without touching other lines (or printing secrets)."""
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    out, done = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == key:
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("id", nargs="?", help="the same id you used for make_manifest.py")
    ap.add_argument("--link", action="store_true", help="symlink plugins instead of copying")
    ap.add_argument("--no-alert", action="store_true", help="don't install fallback-alert")
    only = ap.add_mutually_exclusive_group()
    only.add_argument("--tools-only", action="store_true", help="install only slack-tools; leave slash namespace and alerts untouched")
    only.add_argument("--forwarded-only", action="store_true", help="install only slack-forwarded; preserve existing plugins and namespace")
    ap.add_argument("--with-forwarded", action="store_true", help="also install optional slack-forwarded with the namespace/alert kit")
    a = ap.parse_args()
    if not (a.tools_only or a.forwarded_only) and not a.id:
        ap.error("id is required unless --tools-only or --forwarded-only is used")
    if a.with_forwarded and (a.tools_only or a.forwarded_only):
        ap.error("--with-forwarded cannot be combined with an only mode")
    ident = a.id.strip().lower() if a.id else ""

    env_path = Path(run("config", "env-path"))
    home = env_path.parent
    dest_root = home / "plugins"
    dest_root.mkdir(parents=True, exist_ok=True)

    names = (["slack-tools"] if a.tools_only else ["slack-forwarded"] if a.forwarded_only
             else PLUGINS + (["slack-forwarded"] if a.with_forwarded else []))
    for name in names:
        if name == "fallback-alert" and a.no_alert:
            continue
        src, dest = KIT / "plugins" / name, dest_root / name
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        elif dest.exists():
            shutil.rmtree(dest)
        if a.link:
            os.symlink(src, dest, target_is_directory=True)
        else:
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))
        run("plugins", "enable", name)
        print(f"  {'linked' if a.link else 'copied'} + enabled  {name}")

    if a.forwarded_only:
        print("Next: restart the gateway when ready to load slack-forwarded. Gateway not restarted; namespace unchanged.")
        return
    if a.tools_only:
        print("Next: configure slack-tools settings, then hermes tools enable slack --platform slack. See docs/slack-tools.md. Gateway not restarted.")
        return
    set_env(env_path, "HERMES_SLACK_SLASH", f"hermes-{ident}")
    print(f"  set HERMES_SLACK_SLASH=hermes-{ident} in {env_path}")
    print("\nNext: hermes gateway restart   (then try  /hermes-%s help  in Slack)" % ident)


if __name__ == "__main__":
    main()
