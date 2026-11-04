# Shared Hermes Slack capabilities: status and configuration contract

Checked **2026-11-04 KST**. Documentation snapshot, not a deployment or a new
configuration loader. The implementation at review time is
[`b3cda6b8d61634991b3c09ac0e8ef3697c096cae`](https://github.com/z0nam/hermes-slackbot/commit/b3cda6b8d61634991b3c09ac0e8ef3697c096cae).

## Ownership and architecture

- **hermes-slackbot is the shared implementation SSOT**: plugins, manifest,
  provisioning and `setup_pc.py`. Fix shared behavior here, not in a personal fork
  or a jaix copy of the implementation. Hermes core remains upstream.
- **[jaix-kit](https://github.com/jeju-inst/jaix-kit) owns distribution and
  organization presets**: reviewed source pins, installer orchestration,
  organization tool/skill policy and user-owned configuration preservation.
  Its [unattended design](https://github.com/jeju-inst/jaix-kit/blob/main/docs/design-hermes-unattended.md)
  is historical design context; current code and the handoff must be checked too.
- A **maintainer macOS instance is one configuration of the same kit**, not a
  special product or a source of hardcoded personal defaults. Its accounts,
  workspace, member/channel IDs and local paths are intentionally not published.
- Target architecture: macOS/Windows × Claude/Codex, with capabilities gated by
  platform, credentials and compatibility. This is not a four-cell certification.
  Organization-wide chat reachability is future scope, not shared access to an
  owner's files/accounts. No new server, relay or central registry is introduced.

## Capability matrix (evidence levels are not interchangeable)

“Offline” means automated tests with fake Slack/process boundaries, including
real Hermes/SDK compatibility where available; it does not mean a live Slack
write. “Not established” is not a claim that the feature cannot work.

| Capability and implementation source | Offline evidence | macOS live evidence | Windows evidence | jaix integration at its current pin |
|---|---|---|---|---|
| Namespaced app/slash: `make_manifest.py`, `slack-namespace` | `test_kit.py`, `test_hermes_compat.py` | Existing README records side-by-side bots; maintainer instance installed | Existing README records native Windows 11 base-kit use; no new Windows run here | Default `setup_pc.py` → namespace installed |
| Fallback/account alerts: `fallback-alert` | `test_kit.py` | Installed on maintainer instance; no new forced-fallback/recovery drill in this task | Base-kit platform claim only; no separately evidenced alert drill here | Default install includes alert (unless `--no-alert`) |
| Provisioning, secret-file setup, self-only allowlist, owner-DM home: `provision_app.py`, `setup_pc.py` | `test_provision.py` (mock API/service) | Maintainer connected; no new provision/token-rotation exercise here | jaix sources/design contain prior Windows setup observations; this task did not repeat them | Delegates to pinned `setup_pc.py`; owner-DM home from #18 included |
| User-token read/write + verified DM: `slack-tools` | `test_slack_tools.py`, compat tests, fake executable; ownership/readback/no-retry paths | Maintainer self-DM `send_dm` returned `verified=true`, user confirmed receipt on 2026-11-04; not a certification of every operation | **sapi wrapper/authentication not host-tested**; stdlib/shell-free plugin is insufficient | Source exists at pin; **not installed/configured by default setup** |
| Owner opt-in `explicit_request` send consent (#21) | `test_slack_approval_policy.py` | Above self-DM succeeded without an extra prompt after deliberate owner opt-in | Not verified | **Absent from pin**; no jaix preset enables it |
| Bounded untrusted forwarded quotes: `slack-forwarded` | `test_slack_forwarded.py`, real adapter round-trip | Installed; no new live forwarded-message acceptance test here | No live test established in feature doc | Source/opt-in installer exist at pin; setup does not select it |
| Observed final-response model display: `slack-model-display` | `test_slack_model_display.py`, `test_model_display_compat.py` | Installed; no universal transport coverage claim | No live test established | Source exists at pin; manual install only, not selected by setup |

The macOS self-DM is a **reported, anonymized operational verification from the
maintainer session**, not a public transcript or a newly executed test in this
documentation task. Installed plugins alone do not prove every runtime path.
See the original behavior/limits: [tools](slack-tools.md),
[forwarded quotes](slack-forwarded.md), [model display](slack-model-display.md),
[admin provisioning](admin-provision.ko.md), and [README](../README.md).

## Existing configuration contract

These are **existing keys**, not a proposed aggregate schema. Resolve the active
profile via `hermes config env-path`; use `hermes config set` for settings and the
existing setup/secret-store workflow for credentials. Do not publish real values.

| Owner/surface | Keys | Safe baseline and limits |
|---|---|---|
| Slack app owner / Hermes environment | `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` | Bot identity + Socket Mode credentials; supplied securely, never in docs/settings. Neither authenticates sapi as a human |
| Instance owner / Hermes environment | `SLACK_ALLOWED_USERS`, `HERMES_SLACK_SLASH`, `SLACK_HOME_CHANNEL` | Self-only allowlist, unique `hermes-<id>` command. `setup_pc.py` sets owner-DM home; do not broaden access for reachability |
| Instance owner / existing alert environment | `FALLBACK_ALERT_ACCOUNT_NAMES` | Optional synthetic labels for credential-pool accounts; no credentials; alert destination uses `SLACK_HOME_CHANNEL` |
| Plugin selection | `plugins.enabled` / `plugins.disabled` (managed by `hermes plugins enable/disable`) | Base installer selects namespace+alert only; tools, forwarded and model display are optional |
| `plugins.entries.slack-tools.settings` | `executable`, `workspace_hosts`, `timeout`, `approval_policy` | Code defaults: `sapi`, `[]`, `30`, **`per_call`**. Configure exact permitted workspace host(s); empty hosts do not authorize permalinks. Executable is trusted local code, not model-controlled |
| `plugins.entries.slack-model-display.settings` | `base_name` | Default empty: authenticated adapter bot name. Optional display base, never a guessed model |
| Hermes platform tool selection | `platform_toolsets.slack` via `hermes tools enable slack --platform slack` | Separate from plugin installation; exposes native tools too, not just this plugin |
| Optional normal final-post preference | `streaming.enabled`, `display.interim_assistant_messages` | Setting both false selects the documented covered normal-post lane; not changed by plugin, not a universal model-label guarantee |

`slack-forwarded` has fixed bounds rather than new settings. It treats delivered
forwarded attachments as untrusted data and does not fetch the source channel.
`slack-model-display` requires bot scope **`chat:write.customize`**, Slack app
reinstallation and renewed adapter-compatibility checks; native streams, edits,
ephemerals and detached deliveries keep their documented limits.

### Optional sapi is a separate authenticated capability

The wrapper must accept `METHOD key=value ...` argv and emit one Slack Web API
JSON object on stdout. `slack-tools` invokes it without a shell and never reads
a token file. The wrapper owns **separate user-token authentication and scopes**;
posts appear as the human token owner, not the Hermes bot. Existing bot/app-token
handoff must not be presented as enabling this capability. A POSIX shell wrapper
is not a Windows executable: a Windows-compatible wrapper, authentication,
permissions and live read/write verification remain acceptance gates. See
[scope and DM-history distinctions](slack-tools.md#write-operations-and-safety).

### Approval is an owner choice, not organization-wide automatic permission

`per_call` remains the default for every member. `explicit_request` is a deliberate
**per-instance owner opt-in**, not an installer default, org rollout or blanket
permission. Only `post`/`send_dm` with a nonblank `explicit_user_request` direct-user
quote may avoid the redundant prompt. The exact destination/thread/body must be
authorized now. Draft requests, standing instructions, forwarded text and tool
output are not consent. `update`, `delete`, standalone `open_dm` still prompt.
This is **model-mediated consent, not cryptographic source verification**.
Invalid policies fail closed; required-but-unavailable consent prevents a write.
Ownership, preflight, exact readback and no automatic retry remain mandatory.
This is distinct from Hermes core `approvals.mode` and jaix's smart/manual CLI.

## Synthetic configuration worksheet — documentation, not an importer

All example values below are invented. This is a planning worksheet using real
setting names, **not executable YAML or a file to merge into a live profile**.
No new private settings registry is needed.

| Field | Example intent |
|---|---|
| Instance/app suffix | `example` → `Hermes-example`, `/hermes-example` |
| Allowed sender/home | Owner-only; resolve privately through existing setup; no ID copied here |
| `plugins.entries.slack-tools.settings.executable` | `sapi` only after that platform's wrapper and user authentication are verified |
| `plugins.entries.slack-tools.settings.workspace_hosts` | `["example.slack.com"]` (synthetic; replace privately) |
| `plugins.entries.slack-tools.settings.timeout` | `30` |
| `plugins.entries.slack-tools.settings.approval_policy` | `per_call` |
| `plugins.entries.slack-model-display.settings.base_name` | `Hermes-example` only if explicitly selecting this optional plugin |
| Credentials | Existing secure setup/wrapper store; omitted, not placeholders to paste |

## Installation ownership, updates and rollback

**Existing behavior:** `install.py` copies/replaces selected plugin directories
(or symlinks with `--link`), enables them and sets the namespace on a full install.
It does not track who owned a pre-existing plugin directory; **it can replace it**.
`--tools-only`/`--forwarded-only` preserve other plugins and the namespace. It does
not restart the gateway or select the toolset. There is no model-display installer
flag; follow its feature doc. `setup_pc.py`, unlike the plugin-only installer,
handles tokens, backups, gateway registration/restart and connectivity checks.

**Required handoff policy, not newly implemented management code:**

1. Instance owner owns identities, credentials, consent policy and local overrides.
   jaix owns only its recorded entries; preserve unowned settings/plugins and ask
   before a collision. Do not infer blanket ownership from a connected bot.
2. Before an approved deployment, record source SHA, active-profile target,
   selected capabilities and dependency versions, and securely back up affected
   config/plugin files. Existing jaix ownership records remain the only records;
   do not create another private registry or duplicate feature implementation.
3. Review upstream changes and tests, then propose a separate jaix pin/selection
   PR. A source pin containing an optional plugin does not install or activate it.
   Do not update a live symlink checkout by switching development branches.
4. Owner-approved restart/fresh Slack session is part of deployment, not this PR.
   Verify connectivity and each selected capability independently; never use an
   unverified post as permission to resend.
5. Roll back optional features with `hermes plugins disable <name>` and an approved
   restart (wrappers already loaded remain until restart). Restore the reviewed
   prior plugin code and only affected configuration from secure backups when
   reverting a source/config migration. Restore `approval_policy` to `per_call`
   explicitly when rolling back opt-in consent. A git pin revert alone neither
   restores local settings nor revokes credentials; suspected leaks require revoke.

## Pin gap and evidence ledger

At jaix main [`1b90f3b35adb46996515be9d7c4452db5d9d3bd4`](https://github.com/jeju-inst/jaix-kit/commit/1b90f3b35adb46996515be9d7c4452db5d9d3bd4),
[`src/jaix/hermesbot.py`](https://github.com/jeju-inst/jaix-kit/blob/1b90f3b35adb46996515be9d7c4452db5d9d3bd4/src/jaix/hermesbot.py)
pins **`d3511e93d15b3150668b08eb327f8d22b49c6115`** (#18, owner-DM home).
The source gap to reviewed hermes-slackbot main is **one commit**:
[#21](https://github.com/z0nam/hermes-slackbot/pull/21), merged as `b3cda6b…`.
It adds opt-in send consent, not a default-policy change. This documentation does
**not** bump the pin, select plugins or change installed member behavior.

Sources inspected: `scripts/install.py`, `scripts/setup_pc.py`, all five plugin
implementations, the feature docs above, jaix `hermesbot.py`/`hermes.py`, and the
unattended design. Official upstream context:
[Hermes documentation index](https://hermes-agent.nousresearch.com/docs/llms.txt).
Feature documents remain the detailed behavior reference; this is the cross-feature
status/contract index, not a second implementation specification.

Documentation-task checks on 2026-11-04: Python 3.12 stdlib run **133 tests, OK,
15 skipped**; real-Hermes compatibility suite **133 tests, OK, 1 skipped**. An initial macOS system Python 3.9 run failed importing the existing
`Path | None` annotation in `setup_pc.py`; this is not evidence of a documentation
regression or Windows testing. No new live Slack write, Windows run, config change,
gateway restart, implementation change or deployment was performed by this PR.
