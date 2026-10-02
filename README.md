# hermes-slackbot

> Kit for running your **personal [Hermes Agent](https://github.com/NousResearch/hermes-agent) as a Slack bot** in a workspace where other people run theirs too.
> Independent project — not affiliated with Nous Research.

[한국어 안내](docs/ko.md) · [Hermes에게 설치를 맡기는 프롬프트 (한국어)](docs/hermes-prompt.ko.md)

## The problem

Following the stock setup (`hermes slack manifest --agent-view --write`) gives every personal bot:

- **~50 workspace-wide slash commands** (`/hermes`, `/help`, `/new`, `/model`, …). The second person to install collides with the first, and the most recently installed app takes the commands over. Slack shows the admin a "this app's commands now override …" notice.
- **The same name, `Hermes`.** With several of them nobody can tell whose bot is whose, and people mistake a personal agent — which runs with its owner's files, shell and accounts — for a shared one.

## What this kit does

Each person gets **`Hermes-<id>`** as the app name and **one** command, **`/hermes-<id>`**, used with subcommands:

```
/hermes-alice new            → /new
/hermes-alice model opus     → /model opus
/hermes-alice what's next?   → a normal message
/hermes-alice                → /help
```

| Piece | What it is |
|---|---|
| `scripts/make_manifest.py` | Builds the Slack app manifest from **your installed Hermes** (scopes/events stay in sync) and swaps in the per-user name + single command. |
| `plugins/slack-namespace` | Hermes plugin that answers `/hermes-<id>` and hands it to Hermes' built-in `/hermes` handling. Required — without it Slack says *"app did not respond"*. |
| `plugins/fallback-alert` | Optional. One Slack message to your home channel when Hermes falls back to another model/provider (and when it recovers), or when a credential pool moves to its next account. |
| `scripts/install.py` | Copies (or links) the plugins into your Hermes, enables them, sets `HERMES_SLACK_SLASH`. |

Everything is stdlib Python and works on **Windows, macOS and Linux** — paths are resolved through `hermes config env-path`, never hardcoded.

## Setup

Prerequisites: Hermes Agent installed (`hermes --version`), Python 3, a model configured.

```sh
git clone https://github.com/z0nam/hermes-slackbot
cd hermes-slackbot

# 1. Manifest (pick a short lowercase id — your Slack handle works)
python scripts/make_manifest.py alice --out slack-manifest.json
```

2. **Create the Slack app** — <https://api.slack.com/apps> → *Create New App* → *From a manifest* → choose the workspace → paste `slack-manifest.json` → *Create* → *Install to Workspace*.
   - *Basic Information* → *App-Level Tokens* → generate one with `connections:write` → copy the **`xapp-…`** token.
   - *OAuth & Permissions* → copy the **Bot User OAuth Token `xoxb-…`**.
   - Your **Member ID**: in Slack, your profile → ⋮ → *Copy member ID* (`U…`).

```sh
# 3. Tokens + allow only yourself  (choose Slack; paste xoxb, xapp, your U… id)
hermes gateway setup

# 4. Plugins
python scripts/install.py alice

# 5. Run it as a service and restart
hermes gateway install
hermes gateway restart
```

6. In Slack: DM the bot, then try `/hermes-alice help`.

**Lock it to yourself.** Your Hermes acts with your machine's files, shell and logged-in accounts. Keep `SLACK_ALLOWED_USERS` to your own Member ID.

### Already have a stock Hermes app?

Re-run step 1 with your id, then in your app: *Features → App Manifest → Edit*, replace the contents, *Save*, reinstall when prompted. Then steps 4–5. If the name doesn't change, also check *Basic Information → Display Information* and *App Home*.

## fallback-alert options

Set in your Hermes `.env` (`hermes config env-path` shows where):

```
FALLBACK_ALERT_ACCOUNT_NAMES=personal=Personal,anthropic-oauth-2=Work
```

Labels come from `hermes auth list`. Alerts go to `SLACK_HOME_CHANNEL` (set by `hermes gateway setup` or `/sethome`). Fallback alerts are skipped for Slack sessions, since their thread already shows Hermes' own notice; account-switch alerts are global.

## Notes and limits

- Tested against Hermes Agent 2026-10 (Socket Mode, Agent view). The plugin relies on the Slack adapter's `_handle_slash_command`; if a Hermes update renames it, the plugin logs a warning instead of breaking the gateway.
- One app per person is still Hermes' supported model for self-hosted bots. The longer-term answer for organisations is [Hermes Relay](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/relay) (one shared bot fronting many agents), which is experimental today.

## Development

```sh
python -m unittest discover -s tests                                   # stdlib only
HERMES_AGENT_DIR=~/.hermes/hermes-agent ~/.hermes/hermes-agent/venv/bin/python -m unittest discover -s tests
python scripts/install.py <id> --link                                  # live-edit the plugins
```

## License

MIT
