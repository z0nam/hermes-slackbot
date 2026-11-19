#!/usr/bin/env python3
"""One-shot Slack reminder from the owner's own Hermes bot (no LLM, no admin token).

    python remind.py "2026-11-20T09:00" "도청에 v4 보내기"     # local wall clock (Hermes timezone)
    python remind.py "in 30m" "회의 자료 출력"

Uses Hermes' own scheduler: writes a tiny print-only script under <hermes home>/scripts/remind/
and registers `hermes cron create <when> --no-agent --deliver slack --script remind/<id>.py`.
At the due time the gateway runs it and the bot posts the text to its home channel — the owner's
DM, set by setup_pc.py — so it arrives as a normal bot DM with a phone notification.

Why not the Slack MCP `slack_schedule_message` into your own DM: it goes through the "Claude"
Slack app and Slack then asks to move the conversation to a channel with @Claude.
The gateway must be running at the due time (the PC on).
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import install  # noqa: E402

MAX_TEXT = 3000


def script_body(text: str) -> str:
    """Print-only job script; stdout is delivered verbatim. (pure — for tests)"""
    return ("import sys\n"
            "try:\n    sys.stdout.reconfigure(encoding='utf-8')\nexcept Exception:\n    pass\n"
            f"print({text!r})\n")


def job_name(text: str) -> str:
    """Short label for `hermes cron list`. (pure — for tests)"""
    first = re.sub(r"\s+", " ", text).strip()
    return "remind: " + (first[:40] + "…" if len(first) > 40 else first)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("when", help="ISO local time like 2026-11-20T09:00, or 'in 30m' / 'in 2h'")
    ap.add_argument("text", help="what the bot should say")
    a = ap.parse_args()
    text = a.text.strip()
    if not text:
        sys.exit("empty reminder text")
    if len(text) > MAX_TEXT:
        sys.exit(f"reminder text too long ({len(text)} > {MAX_TEXT} chars)")
    when = a.when.strip()
    if not (when.lower().startswith("in ") or re.match(r"^\d{4}-\d{2}-\d{2}", when)):
        sys.exit("when must be a one-time moment: 2026-11-20T09:00 or 'in 30m' (recurring is not a reminder)")

    home = Path(install.run("config", "env-path")).parent
    rel = f"remind/{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000:06d}.py"
    path = home / "scripts" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script_body(text), encoding="utf-8")
    try:
        out = install.run("cron", "create", when, "--name", job_name(text), "--deliver", "slack",
                          "--no-agent", "--script", rel)
    except SystemExit:
        path.unlink(missing_ok=True)
        raise
    print(out)
    print("Reminder set; the bot will DM you then. List: hermes cron list · cancel: hermes cron remove <id>")


if __name__ == "__main__":
    main()
