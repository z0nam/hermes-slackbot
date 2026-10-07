# AGENTS.md — hermes-slackbot

Guide for AI coding agents (Claude Code, Codex, Hermes, agy) working in this repo. Human docs: `README.md`, `docs/ko.md`.

## What this is

A kit of **Hermes Agent user plugins + stdlib scripts** for running a personal Hermes as a Slack bot in a shared workspace. It is not a fork of Hermes — never patch Hermes core from here; if something needs a core change, say so and stop.

| Path | Notes |
|---|---|
| `plugins/slack-namespace` | `/hermes-<id>` → built-in `/hermes`. Must be a **platform handler** (`register_platform_handler`): the Slack adapter only acks its own command names, so a `pre_gateway_dispatch` rewrite never sees `/hermes-<id>` (tried, failed live). |
| `plugins/fallback-alert` | `post_api_request` hook. Posts on a **non-daemon** thread so one-shot CLI/cron processes don't drop the alert. |
| `plugins/slack-tools` | Optional `sapi` user-token tools. Posts appear as the **human**, not the bot — writes stay human-confirmed. |
| `plugins/slack-forwarded` | Optional; restores Slack "Forward message" attachments as bounded, untrusted quotes. |
| `scripts/make_manifest.py` | Derives the manifest from the installed Hermes; only renames and keeps one command. Slash-command description is a fixed string (Slack caps it at 75 chars). |
| `scripts/install.py` | Resolves paths via `hermes config env-path` — never hardcode `~/.hermes` (Windows uses `%LOCALAPPDATA%\hermes`). |

## Tests

```sh
python3 -m unittest discover -s tests                     # stdlib only; Hermes-dependent cases skip
HERMES_AGENT_DIR=~/.hermes/hermes-agent ~/.hermes/hermes-agent/venv/bin/python -m unittest discover -s tests
```

- **Run the second form too** before claiming done — it exercises real Hermes plugin discovery and the Slack adapter round-trip.
- **Pitfall:** inside a cmux terminal `HERMES_PYTHON` points at a bash wrapper (`cmux-hermes-python-wrapper`), and `tests/test_hermes_compat.py` honours `HERMES_PYTHON`, so `python -c` gets run by bash and two compat tests fail with `import: command not found`. Prefix with `env -u HERMES_PYTHON` (or set it to the real venv python). This is an environment issue, not a code failure.
- A new test for a bug fix should **fail on the old code** first; say so in the PR.

## Live system — be careful

On the maintainer's Mac, `~/.hermes/plugins/<name>` are **symlinks into this checkout** (`install.py <id> --link`), and the gateway (`ai.hermes.gateway`, launchd) loads them. So:

- **Do not switch branches in `~/dev/hermes-slackbot`** — that changes the running bot's code. Work in a `git worktree` (e.g. under `~/.hermes/cache/scratch/`) and leave the main checkout on `main`.
- After a merge: `git -C ~/dev/hermes-slackbot pull`, then `hermes gateway restart`, then check `~/.hermes/logs/gateway.log` for `slack-namespace: /hermes-namun -> /hermes handler registered` and `slack connected`.
- Never print `xoxb-` / `xapp-` / user tokens; `.env` and `auth.json` stay unread except for presence checks.

## Changes

- **Branch → PR, always.** No direct pushes to `main`. The maintainer merges unless they explicitly say "merge it".
- Codex review runs on every PR — check inline comments (`gh api repos/z0nam/hermes-slackbot/pulls/<n>/comments`) and reply with what you changed.
- PR body ends with a signature line: `작성: 조남운 · <agent>/<session> · <YYYY-MM-DD>`.
- This repo is **public**: no member/channel IDs, workspace names, personal emails or tokens in code, tests or docs. Personal values go in the user's Hermes `.env` (e.g. `FALLBACK_ALERT_ACCOUNT_NAMES`).
- Teammates are on **Windows**. Anything user-facing (docs, prompts in `docs/hermes-prompt.ko.md`) must work in PowerShell; keep scripts stdlib-only.
