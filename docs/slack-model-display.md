# Optional per-response Slack display names

`slack-model-display` adds the **observed response model** to ordinary bot response posts, for example `Hermes-example (gpt-6.1-sol)` or `Hermes-example (claude-sonnet-5-5)`. It changes only the `username` field of the existing `chat.postMessage` payload. It never renames the bot profile and makes no additional Slack or LLM calls in the send path. It is opt-in and is not installed by the default kit installer.

## Install (PowerShell)

Run from this repository after reviewing the plugin. Add **`chat:write.customize`** under your Slack app's **OAuth & Permissions → Bot Token Scopes**, reinstall the app, and ensure Hermes uses the resulting bot token. Do not put tokens in commands, this repository, or `config.yaml`.

```powershell
$hermesHome = Split-Path (hermes config env-path)
$plugins = Join-Path $hermesHome "plugins"
New-Item -ItemType Directory -Force $plugins | Out-Null
Copy-Item -Recurse .\plugins\slack-model-display $plugins
hermes plugins enable slack-model-display
hermes config set plugins.entries.slack-model-display.settings.base_name "Hermes-example"
```

For macOS/Linux, the equivalent first-install copy is:

```sh
hermes_home="$(dirname "$(hermes config env-path)")"
mkdir -p "$hermes_home/plugins"
cp -R plugins/slack-model-display "$hermes_home/plugins/"
hermes plugins enable slack-model-display
hermes config set plugins.entries.slack-model-display.settings.base_name "Hermes-example"
```

Use your own base display name. When `base_name` is empty, the adapter's already-authenticated workspace bot name is used; this can be a Slack username rather than the styled display name. No profile lookup is added. Unlabelled messages retain the existing Slack bot identity, not an invented model suffix.

Installation/configuration alone does not restart the gateway. **After approving deployment**, run `hermes gateway restart`. Disabling also requires an approved restart to remove the instance-local adapter wrappers:

```sh
hermes plugins disable slack-model-display
```

## Model attribution and isolation

- `pre_gateway_dispatch` creates a fresh task-local response envelope for each Slack ingress. It is shared through the gateway's copied executor context and Hermes' bounded hook worker contexts. There is no global last-model variable, session cache, or config-based model guess.
- `pre_api_request` invalidates older response evidence and records the current session. `post_api_request` records only the actual `response_model` and the assistant content. Delegated child agents cannot overwrite the parent evidence; mismatched session responses are ignored.
- The instance-local `_post_chunks` wrapper matches the outgoing content against the observed response, allowing only surrounding whitespace trimming. It consumes the evidence once, then adds the same name to every chunk and the adapter's existing Block Kit rejection retry. Other notices and interactive messages do not inherit a cached model.
- Missing/invalid response models, tool-call responses, unmatched/rewritten content, or absent turn context use the base bot identity. Model identifiers are preserved exactly, not shortened or replaced with the configured model. Unsupported identifiers (control characters, whitespace, parentheses, or more than 160 characters) are omitted rather than repaired.

## Transport coverage and limits

| Path | Behaviour |
|---|---|
| Ordinary `send` → `_post_chunks` → `chat.postMessage` | Observed model suffix, including adapter chunking and Block Kit rejection retry |
| Native `chat.startStream` / append / stop | Base identity; the message starts before a confirmed response model exists |
| Edit-based streaming | Initial unknown-model posts stay base identity; `chat.update` is not given `username` |
| Existing-message edits | Existing identity unchanged; no additional post/delete/recreate to change it |
| Slash response URL / ephemeral replies, private notices, interactive cards | Unchanged base identity |
| File uploads and standalone cron Slack delivery | Unchanged; these bypass this per-turn adapter path |
| Internal events without normal ingress, detached/background delivery, gateway-generated media-tag rewrites or splits | Base identity when there is no matching response evidence; no guessed attribution |

This is deliberately **not a universal streaming-model badge**. It prioritizes avoiding an incorrect model name over labelling every message. It does not change streaming configuration. To see suffixes consistently, use a non-streaming response transport configured through Hermes' supported configuration interface; the plugin does not silently disable streaming or buffer responses. A small `send` wrapper also clears matching evidence when a completed stream or ephemeral delivery bypasses `_post_chunks`, so later system notices cannot reuse it. On an unsupported Hermes adapter without `_post_chunks` / `_call_with_block_fallback`, the factory stays inactive. If Hermes' delegated-child context guard is unavailable, attribution is disabled rather than guessing. These are private adapter interfaces, so rerun compatibility tests after upgrading Hermes.

The independent `fallback-alert` plugin and its existing alert behaviour are untouched; this feature does not fix or close issue #9.

## Offline verification

```sh
python -m unittest discover -s tests
```

The full Hermes compatibility suite uses `HERMES_AGENT_DIR` and optionally `HERMES_PYTHON` (the actual Python executable, not a shell wrapper):

```powershell
$env:HERMES_AGENT_DIR = "C:\path\to\hermes-agent"
$env:HERMES_PYTHON = "C:\path\to\hermes-agent\venv\Scripts\python.exe"
& $env:HERMES_PYTHON -m unittest discover -s tests
```

`test_model_display_compat.py` additionally requires `slack-sdk`, `slack-bolt`, and `aiohttp`. It exercises real Hermes plugin discovery/lifecycle dispatch, copied executor and bounded hook worker contexts, the native Slack adapter, and actual async Slack SDK payload building. Only the SDK HTTP boundary is replaced with an offline response. It verifies concurrent sessions in the same channel, child isolation, one Slack call per normal send, unknown-model system messages, block retries, chunking, edits, and native streams without an incorrect suffix. Without the SDK dependencies that test explicitly skips; a skipped SDK test is not proof of SDK compatibility. No live messages are posted by these tests.
