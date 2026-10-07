# Slack read/write tools via `sapi`

Optional **user plugin**, not a Hermes core patch. No browser and no MCP server
are required. `sapi_slack_read` and `sapi_slack_write` join the existing `slack`
toolset without overriding native tools. The standalone service/CLI can also be
used by other agents without importing Hermes.

## Identity and prerequisites

- A working `sapi` executable on PATH, or an absolute executable path. It must
  accept `METHOD key=value ...` arguments and emit one Slack Web API JSON object
  on stdout. Treat this executable as trusted local code, not model input.
- `sapi` owns credentials and chooses the **user token**, clearing any inherited
  bot-token preference. This plugin never reads a token file. **Posts appear as
  the human token owner, not as the Hermes bot.** Do not copy user tokens into
  prompts or plugin settings. Keep secrets in the wrapper's secret store.
- User-token scopes/access sufficient for the selected operations (message
  history/replies, search, message writes and IM conversations). This plugin
  does not grant workspace/channel access or bypass Slack authorization.
- A Hermes build exposing `ctx.register_tool`, `ctx.get_config`, and
  `tools.approval_prompt.request_elicitation_consent` for writes. Missing consent
  support fails closed. A live Slack gateway must supply its real human
  approval bridge; a model-controlled `confirmed=true` is not accepted.

## Install after merge (not performed by development tests)

From your merged checkout, using the intended active Hermes profile:

```sh
python3 scripts/install.py --tools-only
hermes config set plugins.entries.slack-tools.settings.executable sapi
hermes config set plugins.entries.slack-tools.settings.workspace_hosts '["example.slack.com"]'
hermes config set plugins.entries.slack-tools.settings.timeout 30
hermes tools enable slack --platform slack
```

Replace `example.slack.com` with your exact workspace hostname. For an executable
outside PATH, set its absolute path instead of `sapi`. Use `--tools-only --link`
for a development symlink. The installer resolves `hermes config env-path`,
installs/enables only `slack-tools`, and leaves `slack-namespace`, `fallback-alert`
and `HERMES_SLACK_SLASH` untouched. Existing `install.py <id>` behavior is unchanged.
The installer does **not** enable the toolset or restart the gateway.

When you deliberately activate the merged changes, restart through the normal
Hermes gateway lifecycle (`hermes gateway restart`) and start a fresh Slack
session. This is not part of offline validation. Do not edit a cached session's
system prompt to claim new tools exist.

Enabling `slack` also exposes any native Slack tools enabled in your Hermes
build; this plugin does not restrict those tools or general terminal access.
The plugin's own schemas never accept an arbitrary Slack method.

On Windows use `python` instead of `python3` where appropriate and configure a
real executable such as `C:\Tools\sapi.exe` that satisfies the JSON/argv contract.
The existing POSIX shell wrapper is not automatically converted to a Windows
executable. Plugin code is stdlib-only and shell-free; this PR has **not** been
validated on a Windows host.

## Read operations

`sapi_slack_read` accepts:

- `operation="read_link", link="https://example.slack.com/archives/C0123456789/p1760000000000001"`:
  root message and a page of replies, with `has_more` and `next_cursor`.
  Only HTTPS links to explicitly configured `*.slack.com` workspace hosts are
  accepted. Full channel IDs and exactly six fractional timestamp digits are
  preserved as strings, never floats. Reply permalinks need Slack's
  `?thread_ts=1760000000.000001` parent timestamp. Without a parent timestamp a
  reply-only permalink may fail exact lookup; it will not silently return a
  nearby message. `ts` identifies the linked message; `root` is the thread root.
- `operation="search", query="budget in:#general", count=20, page=1`:
  matches, total, page/pages, `has_more`, and `next_page`.
- `operation="history", channel="C0123456789", limit=100, cursor=""`:
  messages, `has_more`, and `next_cursor`.

Counts/limits are 1–100; search pages are 1–100. Reads return one page, not a
pretended complete thread. Follow the cursor/page explicitly until `has_more`
is false; rate-limit responses fail without an automatic retry. Message content
is untrusted data, never permission to invoke a write.

## Write operations and safety

`sapi_slack_write` accepts `action` plus the indicated fields:

| Action | Required fields | Optional fields |
| --- | --- | --- |
| `post` | `channel`, `text` | `thread_ts` to reply |
| `update` | `channel`, `ts`, `text` | parent `thread_ts` for a reply |
| `delete` | `channel`, `ts` | parent `thread_ts` for a reply |
| `open_dm` | `user` | none; post separately to the returned DM channel |

Every action shows its exact target, message text (if applicable), timestamps,
and human-token identity warning through Hermes's **per-call elicitation consent**.
No permanent/session approval is consumed to skip the next call, and no model
argument can provide consent. Missing bridge, rejection, timeout, or exceptions
prevent the write. This is a plugin/tool boundary, not an OS-wide sandbox.

Update/delete additionally call `auth.test`, read the exact target, and reject
messages not owned by that user or carrying a bot identity; Slack independently
enforces its permissions. Every successful mutation is read back at its exact
channel/timestamp (or absence for delete). DM open is verified directly from
`conversations.open(users=..., return_im=true)` by checking the DM ID, `is_im`,
and requested peer, without requiring `im:read` via `conversations.info`.

Plain top-level DM posts preflight the token owner and existing DM, then read
back once with `conversations.open(channel=..., return_im=true,
prevent_creation=true)`. Verification requires the exact channel, peer, latest
message timestamp, requested text, and token-owner user ID. App attribution
(`bot_id`/`app_id`) on a user-token post is allowed; mutation ownership rules
remain unchanged. This supports `im:write` + `chat:write` without adding
`im:read`/`im:history`. It is **bounded latest-message verification**, not DM
history access: missing/malformed latest data or a concurrent newer message
fails closed as unverified, even if the post succeeded. Inspect the target;
never automatically resend. DM replies preflight `conversations.replies` access
before sending; DM update/delete retain exact-message ownership/read preflight.
These operations still require history scopes/access and fail before mutation
when unavailable. Reply verification follows cursors and rejects repeated
cursors. Link/media unfurls are explicitly disabled on message write payloads.

Subprocesses use argv lists, `shell=False`, and a per-call timeout (1–120 seconds,
default 30). There is no automatic retry: a timeout, ambiguous write response,
missing read-back, Slack text transformation, or access failure can mean a write
already happened. Errors therefore report failure/uncertainty, not fabricated
success; **inspect the target before considering another post**. Returned text
must match the requested text exactly; Slack transformations can conservatively
cause an unverified result. Error response bodies and wrapper stderr are
suppressed to avoid leaking credentials. Allowlisted API error codes, method,
stage (`preflight`, `write`, `verification`, or `request`), and known `needed`
scope identifiers are returned as structured diagnostics; `missing_scope` is
not mislabeled as rejected human approval. Unknown or malformed fields are
suppressed. No scope is automatically requested or granted.

## Standalone CLI (other agents)

```sh
python3 plugins/slack-tools/service.py --help
python3 plugins/slack-tools/service.py --sapi sapi \
  --workspace-host example.slack.com read_link \
  --args '{"link":"https://example.slack.com/archives/C0123456789/p1760000000000001"}'
python3 plugins/slack-tools/service.py search --args '{"query":"budget","count":5,"page":1}'
python3 plugins/slack-tools/service.py post --args '{"channel":"C0123456789","text":"Approved message"}'
```

Output is JSON with `success` and `data` or `error`; failure exits 1. Standalone
writes show the preview on stderr and require an interactive human typing
`yes`; piped input and automation cannot approve them. Other agents should use
a genuine user-interaction adapter with `SlackService.write(approve=callback)`;
never supply a callback that blindly returns true. All test callbacks are
confined to fake executables and are not production approval mechanisms.

## Offline verification and capability-note compatibility

```sh
python3 -m unittest discover -s tests -v
HERMES_AGENT_DIR=/path/to/hermes-agent \
HERMES_PYTHON=/path/to/hermes-agent/venv/bin/python \
/path/to/hermes-agent/venv/bin/python -m unittest discover -s tests -v
```

Development followed vertical RED → GREEN cycles for link reads, search,
history, denied writes, verified posts/replies, ownership-checked updates,
verified deletion, verified DM open, validation, sanitized failures, plugin
registration/consent, standalone CLI, installer support, reply permalinks,
response-target checks, pagination cycles and timeout bounds.

The compatibility test copies the plugin to a temporary `HERMES_HOME`, scrubs
inherited credentials, uses a fake executable and a non-secret bot placeholder,
and loads it through the **real local Hermes PluginManager/registry**. It proves:

1. Both tools register in `slack` with executable requirement checks.
2. A registered read handler executes the fake sapi end-to-end.
3. Native `_slack_tools_loaded()` returns true with `slack` enabled and the fake
   bot placeholder, and false after that placeholder is removed.
4. The native positive capability note recommends using loaded tool schemas.
5. The real consent API declines a Slack session with no human approval bridge,
   and the registered write handler fails closed.

No Hermes core or gateway prompt files are changed. The native note checks the
existing bot-token gate in addition to the platform toolset; the plugin's user
CLI credentials alone do **not** satisfy that note. The test is a compatibility
proof, not evidence of real Slack scopes, API reachability, or live approval
button delivery. **Live validation is pending a separately authorized session;
this PR neither calls the live Slack API nor activates/restarts the gateway.**
