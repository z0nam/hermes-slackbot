# Optional per-response Slack display names

`slack-model-display` adds the **observed response model** to confirmed final-answer posts, for example `Hermes-example (gpt-6.1-sol)` or `Hermes-example (claude-sonnet-5-5)`. A confirmed final whose model cannot be proved uses `Hermes-example (모델 확인 불가)` instead of silently omitting the suffix. Progress, commentary and system notices remain unlabelled. It changes only the `username` field of the existing `chat.postMessage` payload. It never renames the bot profile and makes no additional Slack or LLM calls in the send path. It is opt-in and is not installed by the default kit installer.

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
- `pre_api_request` invalidates older response/final evidence and records the current session and turn. `post_api_request` records the actual `response_model` and assistant content, **but does not authorize a delivery**. Delegated children and mismatched session/turn responses cannot replace the parent evidence.
- `post_llm_call` confirms the final text after the tool loop. An observed model is used only when that final exactly matches the last non-tool response (surrounding whitespace may be trimmed). A transformed/composite final without that exact provider evidence is explicitly unknown, even if a configured model is available.
- The `send` wrapper requires `notify=True`, exact final text, matching ingress channel/workspace/thread, and neither `_interim_send` nor `expect_edits`. It also accepts the **exact result** of the running gateway's final-response sanitizer (redaction / terminal EOS removal). It does not import the gateway entry point, fuzzy-match, substring-match, or label every notification.
- `_post_chunks` adds the same name to every chunk and the existing Block Kit rejection retry. Evidence is consumed only after a successful final delivery, including streams/ephemerals that bypass `_post_chunks`; failed sends retain it for the gateway's existing retry. Identical later system messages cannot reuse successful-delivery evidence.
- Model identifiers are preserved exactly, not shortened or replaced with the configured model. Missing/unsupported identifiers (control characters, whitespace, parentheses, or more than 160 characters) display `모델 확인 불가` on an eligible final. A tool-call response never supplies a model name. Absent final authority or unmatched delivery content stays unlabelled; unknown is **not** a license to label a system notice.

### Why a content-only match was insufficient

Hermes calls `post_api_request` before downstream reasoning/interim callbacks. A matching early send could therefore take the old plugin's one-use evidence before the actual final. Offline coverage deterministically demonstrates this using real response intake, hook-worker dispatch, a controlled downstream callback, the stream consumer's commentary transport and the real Slack SDK HTTP boundary. This proves a vulnerable ordering, not that a particular production message was sent by that callback: the built-in gateway thinking rail adds its own prefix. Final text can also change at the gateway sanitizer, so streaming disabled alone is not a consistency guarantee.

## Transport coverage and limits

| Path | Behaviour |
|---|---|
| Confirmed final `send` → `_post_chunks` → `chat.postMessage` | Observed model suffix or explicit unknown, including chunking, Block Kit retries and gateway sanitizer output |
| Progress / commentary / preview / system notice | Unlabelled; cannot consume final evidence |
| Native `chat.startStream` / append / stop | Existing base identity; no username parameter or additional post/update |
| Edit-based streaming / existing-message edits | Existing identity unchanged; `chat.update` is not given `username` |
| Slash response URL / ephemeral replies, private notices, interactive cards | Existing transport unchanged |
| File uploads and standalone cron Slack delivery | Unchanged; bypass this per-turn adapter path |
| Internal events without ingress, missing final hook, detached/background delivery, gateway media/image/bare-path rewrites or splits | Unlabelled unless the exact confirmed final survives; no guessed attribution |

**This is not a universal “every final is always labelled” guarantee.** The installed hooks expose finalization, not every final wire delivery. A completed commentary message may later be recognized as the final and suppress a separate final send, even when `streaming.enabled=false` and interim messages are enabled. The plugin cannot retroactively rename that earlier message. Native streams start before the observed model/final authority is available, and `chat.update` cannot change a message username. No speculative footer is appended to those early messages; no extra post/delete/recreate calls are made. Under the constraints of unchanged streaming/ephemeral transports and no extra posts/updates, universal coverage needs a final-delivery seam carrying authoritative response identity into each transport; this kit does not patch Hermes core. The supported `transform_llm_output` hook could add a body/footer, but it is first-non-None-wins and this Hermes explicitly reconciles transformed streamed replies with an edit or another final send (`_run_agent_mark_streamed_delivery`). That is not a no-call, unchanged-transport fallback and is not introduced here.

For the covered normal final-post lane, use Hermes' supported configuration interface (never edit configuration files by hand):

```powershell
hermes config set streaming.enabled false
hermes config set display.interim_assistant_messages false
```

These settings are a user choice, not a plugin side effect or a promise of coverage for detached/media/generated replies. Installation/configuration changes require an approved deployment/restart as described above. Without `chat:write.customize`, Slack may reject customized posts; the plugin does not change scopes or silently post a second footer message.

On an unsupported adapter without the private send/chunk/fallback seams, the factory stays inactive. If the delegated-child guard is unavailable, attribution is disabled rather than guessing. The gateway sanitizer is reused only if already loaded; otherwise only exact final text is accepted. Rerun compatibility tests after upgrading Hermes.

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

`test_model_display_compat.py` additionally requires `slack-sdk`, `slack-bolt`, and `aiohttp`. It exercises real Hermes plugin discovery/lifecycle dispatch, copied executor and bounded hook worker contexts, the native Slack adapter, and actual async Slack SDK payload building. Only the SDK HTTP boundary is replaced with an offline response. It verifies actual response-intake hook ordering with a controlled downstream callback, real finalization hooks, gateway sanitization, concurrent sessions in the same channel, child isolation, one Slack call per normal send, explicit unknown finals, unlabelled system messages, block retries, chunking, edits, and native streams without an incorrect suffix. Entry-point dependency adoption/relaunch is disabled in the offline subprocess only; runtime hooks, gateway helpers and SDK payload construction remain real. Without the SDK dependencies that test explicitly skips; a skipped SDK test is not proof of SDK compatibility. No live messages are posted by these tests.
