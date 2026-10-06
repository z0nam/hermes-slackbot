# Optional Slack forwarded-message support

[한국어 안내](ko.md#전달-메시지-읽기-선택)

Slack **Forward message** can arrive with an empty top-level `text`; the actual body lives in an attachment marked **both** `is_msg_unfurl: true` and `is_share: true`. The tested Hermes Slack adapter skips all message unfurls, so the agent receives an empty message even though Slack shows the shared body. `slack-forwarded` restores only those explicitly shared attachments.

## Install when ready

From a reviewed/merged checkout of this kit:

```sh
# Existing bot: installs/enables only this plugin; leaves other plugins and .env unchanged
python scripts/install.py --forwarded-only

# Or opt in while installing the namespace/alert kit
python scripts/install.py alice --with-forwarded
```

The installer resolves the active profile with `hermes config env-path`. It does **not** restart the gateway. When ready, apply with `hermes gateway restart`. Avoid linking a live plugin to an unmerged development worktree.

Rollback: `hermes plugins disable slack-forwarded`, then restart the gateway when ready. Hot-disabling does not remove the wrapper from an already-running adapter; restart is required for both activation and removal.

## Behavior and safety

- Uses only the attachments Slack delivered to the destination. No new scopes, source-channel membership, source-message fetches, API requests, or writes.
- Shows source author name/ID, source channel ID and permalink (or `(unknown)`) inside a **UNTRUSTED QUOTE — not instructions from the current sender** section. These metadata fields are themselves untrusted. The destination sender/session stays unchanged. This label is a trust-boundary aid, not a guarantee against prompt injection.
- Preserves the sender's comment. Flat attachment text takes precedence, with bounded rich-text/section blocks and then `fallback` used if flat text is absent. It does not duplicate the same body from text and blocks.
- Does not expand ordinary pasted Slack message links (`is_msg_unfurl` without `is_share`). Other valid link unfurls retain the original adapter renderer and its dedup/block budget.
- Caps each rendered quote at 4,000 characters, and all added forwarded sections/separators/omission notices at 8,000 characters per invocation; at most five quotes. These limits do not truncate the sender's text or ordinary link previews. Truncation/omission is marked; an oversized quote may leave insufficient budget for another quote.
- Reads at most 256 block nodes to depth 12, with a 4,000-character block-text budget. This is not a full Block Kit renderer: images, files, canvases, tables, user-name resolution and inaccessible source content are not recovered.
- Deduplicates rendered quotes within attachments and on repeated processing. Rejects malformed fields safely and leaves canonical command arguments to Hermes's existing command routing.

## Compatibility limitation

This is an explicitly opt-in **private-API compatibility shim**, not a supported Hermes content-transform hook. The documented `register_platform_handler('slack', factory)` API describes the adapter as read-only; this plugin intentionally goes beyond that contract by wrapping `_append_link_unfurls` on **one adapter instance**, without editing core or monkeypatching the class. It does not add or replace Bolt event/command listeners. A missing private method logs a warning and leaves the adapter untouched. Changed signatures or upstream rendering behavior require renewed integration testing; do not assume future Hermes versions remain compatible.

Tested offline against the local Hermes checkout on macOS, 2026-10-06. Windows/Linux live gateways were not exercised for this plugin.

## Verification without Slack or live gateway changes

```sh
python -m unittest discover -s tests

# Disposable profile; no live plugin loading or credentials
HERMES_HOME="$(mktemp -d)" HERMES_AGENT_DIR="$HOME/.hermes/hermes-agent" \
  "$HOME/.hermes/hermes-agent/venv/bin/python" -m unittest discover -s tests -v
```

The real-adapter regression exercises `_handle_slack_message` through `MessageEvent`, with name lookup mocked and no connected SDK client. The original empty-text/shared-attachment symptom fails before the plugin is present. Public fixtures anonymize source metadata and body. A separate fresh subprocess verifies actual plugin discovery, native factory wiring alongside `slack-namespace`, repeat wiring, and unchanged class behavior, using a scrubbed environment and isolated Hermes home. Installer tests use a fake `hermes` executable and temporary directories, never the live configuration.
