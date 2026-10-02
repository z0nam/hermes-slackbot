#!/usr/bin/env python3
"""Install the kit's plugins into your Hermes and point HERMES_SLACK_SLASH at your command.

    python install.py <id>               # copy plugins, set HERMES_SLACK_SLASH=hermes-<id>, enable
    python install.py <id> --link        # symlink instead of copy (for kit developers)
    python install.py <id> --no-alert    # skip the fallback-alert plugin

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
    ap.add_argument("id", help="the same id you used for make_manifest.py")
    ap.add_argument("--link", action="store_true", help="symlink plugins instead of copying")
    ap.add_argument("--no-alert", action="store_true", help="don't install fallback-alert")
    a = ap.parse_args()
    ident = a.id.strip().lower()

    env_path = Path(run("config", "env-path"))
    home = env_path.parent
    dest_root = home / "plugins"
    dest_root.mkdir(parents=True, exist_ok=True)

    for name in PLUGINS:
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

    set_env(env_path, "HERMES_SLACK_SLASH", f"hermes-{ident}")
    print(f"  set HERMES_SLACK_SLASH=hermes-{ident} in {env_path}")
    print("\nNext: hermes gateway restart   (then try  /hermes-%s help  in Slack)" % ident)


if __name__ == "__main__":
    main()
