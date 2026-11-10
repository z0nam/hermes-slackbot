#!/usr/bin/env python3
"""Admin tool: walk through many new Hermes-<id> apps in one terminal, one person at a time.

After `provision_app.py create` has made the apps, each person still needs three clicks in the
browser and a connection code (JX-…) from `jaix hermes handoff`. This script strings those
together so the admin only clicks and pastes:

    python onboard_batch.py --roster PEOPLE.tsv [--jaix "uv run -q --project ~/dev/jaix-kit jaix"]

For each registered app whose owner (Slack member ID) appears in the roster:
  1. opens the app's Install page — click Allow;
  2. opens Basic Information and OAuth & Permissions — generate the App-Level Token
     (scope connections:write);
  3. runs `jaix hermes handoff <id> --user U…`. The two tokens are pasted into jaix's own hidden
     prompt: this script passes the terminal through and never sees them;
  4. picks the JX code out of jaix's output and appends "name · code" to a 0600 file for the DMs.

Between people: Enter = next, s = skip, q = quit. Progress is kept in a file next to the registry,
so running the same command again resumes where it stopped (done people are not asked again;
skipped ones are). A person who already has a code is never given a second one silently: jaix
stops with exit code 3 and this script asks before re-running it with --again.

The roster is any TSV/CSV with a header row: the first column is the name, and the first cell
that looks like a Slack member ID (U…) is the owner. Keep it outside the repo (it is personal data).
Stdlib only.
"""
import argparse
import csv
import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import provision_app  # noqa: E402

UID_RE = re.compile(r"^U[A-Z0-9]{8,}$")
CODE_RE = re.compile(r"\bJX-[A-Z2-7]{26}\b")
ALREADY_ISSUED = 3  # jaix hermes handoff: a code was issued before; needs --again


# ── pure helpers (tested) ─────────────────────────────────────────────────────

def parse_roster(text: str) -> list:
    """[(name, uid)] in file order. Header row skipped; rows without a member ID ignored."""
    dialect = "excel-tab" if "\t" in text.splitlines()[0] else "excel"
    rows = list(csv.reader(text.splitlines(), dialect=dialect))
    out, seen = [], set()
    for row in rows[1:]:
        cells = [c.strip() for c in row]
        uid = next((c for c in cells if UID_RE.match(c)), None)
        if not cells or not uid or uid in seen:
            continue
        seen.add(uid)
        out.append((cells[0], uid))
    return out


def plan(roster: list, registry: dict, progress: dict, only: set | None = None) -> tuple:
    """(todo, missing): todo = [(name, ident, row)] in roster order, skipping people marked done;
    missing = names in the roster with no registered app."""
    by_uid = {row["user"]: (ident, row) for ident, row in registry.items()}
    todo, missing = [], []
    for name, uid in roster:
        hit = by_uid.get(uid)
        if not hit:
            missing.append(name)
            continue
        ident, row = hit
        if only is not None and ident not in only:
            continue
        if only is None and progress.get(ident, {}).get("status") == "done":
            continue
        todo.append((name, ident, row))
    return todo, missing


def find_code(text: str) -> str | None:
    m = CODE_RE.findall(text)
    return m[-1] if m else None


# ── state files ───────────────────────────────────────────────────────────────

def load_progress(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_progress(path: Path, progress: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def mark(path: Path, progress: dict, ident: str, status: str) -> None:
    progress[ident] = {"status": status, "at": datetime.datetime.now().isoformat(timespec="seconds")}
    save_progress(path, progress)


def append_code(path: Path, name: str, code: str) -> None:
    """One "name · code" line, file created 0600 (codes are single-use but still not for sharing)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(f"{name} · {code}\n")


# ── running jaix ──────────────────────────────────────────────────────────────

def run_handoff(jaix: list, ident: str, user: str, again: bool = False, echo=print) -> tuple:
    """Run `jaix hermes handoff`. stdin/stderr stay on the terminal (jaix reads the tokens there,
    hidden); only stdout is piped so the JX code can be picked out. Returns (exit code, code|None)."""
    cmd = [*jaix, "hermes", "handoff", ident, "--user", user] + (["--again"] if again else [])
    env = dict(os.environ, PYTHONUNBUFFERED="1")  # jaix's prompts must show before its hidden input
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                            bufsize=1, env=env)
    seen = []
    for line in proc.stdout:
        echo(line, end="", flush=True)
        seen.append(line)
    return proc.wait(), find_code("".join(seen))


def expand_home(token: str) -> str:
    """`~/x` and `--opt=~/x` -> absolute. No shell runs the command, so nothing else expands them."""
    key, sep, val = token.partition("=")
    if sep and key.startswith("-") and val.startswith("~"):
        return f"{key}={os.path.expanduser(val)}"
    return os.path.expanduser(token) if token.startswith("~") else token


def resolve_jaix(arg: str | None) -> list:
    if arg:
        return [expand_home(t) for t in shlex.split(arg)]
    found = shutil.which("jaix")
    if not found:
        sys.exit('`jaix` is not on PATH. Pass it explicitly, e.g. --jaix "uv run -q --project ~/dev/jaix-kit jaix"')
    return [found]


# ── the walk ──────────────────────────────────────────────────────────────────

def walk(todo, jaix, progress_path, progress, codes_path, ask=input, open_url=webbrowser.open, echo=print,
         handoff=run_handoff) -> int:
    done = 0
    for i, (name, ident, row) in enumerate(todo, 1):
        echo(f"\n━━ [{i}/{len(todo)}] {name} · Hermes-{ident} ━━")
        choice = ask("Enter = 시작, s = 건너뛰기, q = 중단 > ").strip().lower()
        if choice == "q":
            break
        if choice == "s":
            mark(progress_path, progress, ident, "skipped")
            continue
        pages = dict(provision_app.links(row["app_id"]))
        install = next(u for k, u in pages.items() if k.startswith("1."))
        general = next(u for k, u in pages.items() if k.startswith("2."))
        oauth = next(u for k, u in pages.items() if "xoxb" in k)
        open_url(install)
        ask("① 브라우저에서 [허용]을 누른 뒤 Enter > ")
        open_url(general)
        open_url(oauth)
        ask("② Basic Information에서 App-Level Token(connections:write)을 만든 뒤 Enter > ")
        echo("③ jaix 숨김 입력에 xoxb(OAuth & Permissions)와 xapp(방금 만든 토큰)을 차례로 붙여 넣으세요.")
        again = False
        while True:
            rc, code = handoff(jaix, ident, row["user"], again=again, echo=echo)
            if rc == 0 and code:
                append_code(codes_path, name, code)
                mark(progress_path, progress, ident, "done")
                done += 1
                echo(f"✔ {name}: 코드를 {codes_path} 에 적었습니다.")
                break
            if rc == ALREADY_ISSUED and not again:
                if ask("이미 코드를 낸 사람입니다. --again 으로 다시 낼까요? (y/N) > ").strip().lower() == "y":
                    again = True
                    continue
            else:
                echo(f"✘ jaix 종료 코드 {rc}" + ("" if rc else " (출력에서 JX 코드를 찾지 못함)"))
                if ask("r = 다시 시도, 그 밖 = 건너뛰기 > ").strip().lower() == "r":
                    continue
            mark(progress_path, progress, ident, "skipped")
            break
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roster", required=True, type=Path, help="TSV/CSV with a header: name first, member ID (U…) somewhere")
    ap.add_argument("--jaix", help='command that runs jaix (default: `jaix` on PATH)')
    ap.add_argument("--only", help="comma-separated ids to do (even if marked done)")
    ap.add_argument("--codes", type=Path, help="where to append 'name · code' lines (default: next to the registry)")
    a = ap.parse_args(argv)

    roster = parse_roster(a.roster.read_text(encoding="utf-8-sig"))
    progress_path = provision_app.CONF / "onboard-progress.json"
    progress = load_progress(progress_path)
    only = {s.strip().lower() for s in a.only.split(",")} if a.only else None
    todo, missing = plan(roster, provision_app.load_registry(), progress, only)
    if missing:
        print(f"앱이 없는 사람 {len(missing)}명(건너뜀): {', '.join(missing)}")
    if not todo:
        print("할 사람이 없습니다(모두 끝났거나 앱이 없음).")
        return 0
    jaix = resolve_jaix(a.jaix)
    codes_path = a.codes or provision_app.CONF / f"jx-codes-{datetime.date.today():%Y%m%d}.txt"
    print(f"{len(todo)}명 진행. 진행 기록: {progress_path}")
    try:
        done = walk(todo, jaix, progress_path, progress, codes_path)
    except (KeyboardInterrupt, EOFError):
        print("\n중단했습니다. 같은 명령으로 다시 이어 갈 수 있습니다.")
        return 130
    left = sum(1 for _, ident, _ in todo if progress.get(ident, {}).get("status") != "done")
    print(f"\n이번에 {done}명 완료, 남은 사람 {left}명.")
    if codes_path.exists():
        print(f"DM용 코드 모음: {codes_path}\n  다 보낸 뒤 지우세요:  rm '{codes_path}'  (1회용이지만 남겨 둘 이유가 없습니다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
