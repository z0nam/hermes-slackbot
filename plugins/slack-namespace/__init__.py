"""slack-namespace — one namespaced slash command per personal Hermes Slack app.

Why
    `hermes slack manifest` registers ~50 slash commands (/hermes, /help, /new, /model, ...)
    workspace-wide. When a second person installs their own Hermes app in the same workspace the
    commands collide and the most recently installed app takes them over. Each personal app should
    instead register exactly one command, `/hermes-<id>`, and use subcommands.

How
    The Slack adapter only attaches bolt listeners to its own command names, so an unknown command
    such as `/hermes-<id>` is never acked and Slack reports "app did not respond". (A
    `pre_gateway_dispatch` text rewrite never sees it for that reason.) This plugin registers a
    platform handler that acks `/hermes-<id>` immediately, rewrites the payload's `command` to
    `/hermes`, and hands it to the adapter's built-in handling — which maps `<subcommand> [args]`
    to the gateway command, or treats any other text as a normal question.

        /hermes-<id> new           -> /new
        /hermes-<id> model opus    -> /model opus
        /hermes-<id> what's next?  -> "what's next?" (regular message)
        /hermes-<id>               -> /help

Config
    HERMES_SLACK_SLASH in <HERMES_HOME>/.env, e.g. `HERMES_SLACK_SLASH=hermes-alice`
    (a leading "/" is optional). If unset, the plugin does nothing.
    The command must also be declared in the Slack app manifest (scripts/make_manifest.py).
"""
import logging
import os

logger = logging.getLogger(__name__)


def umbrella_from_env(env=None) -> "str | None":
    """`/hermes-<id>` from HERMES_SLACK_SLASH, or None when unset. (pure — for tests)"""
    raw = ((env if env is not None else os.environ).get("HERMES_SLACK_SLASH") or "").strip().lstrip("/")
    return f"/{raw}" if raw else None


def to_builtin(command: dict) -> dict:
    """Rewrite a `/hermes-<id>` payload into the `/hermes` payload the adapter understands. (pure)"""
    return {**command, "command": "/hermes"}


def _slack_factory(app, adapter) -> None:
    umbrella = umbrella_from_env()
    if not umbrella:
        logger.warning("slack-namespace: HERMES_SLACK_SLASH is not set; no namespaced command registered")
        return
    if umbrella == "/hermes":
        logger.warning("slack-namespace: HERMES_SLACK_SLASH=hermes is the built-in command; nothing to do")
        return

    @app.command(umbrella)
    async def _handle(ack, command):
        await ack(response_type="ephemeral", text=f"{umbrella} …")
        try:
            await adapter._handle_slash_command(to_builtin(command))
        except Exception as exc:  # never take the gateway down over one command
            logger.warning("slack-namespace: handling %s failed: %s", umbrella, exc)

    logger.info("slack-namespace: %s -> /hermes handler registered", umbrella)


def register(ctx) -> None:
    ctx.register_platform_handler("slack", _slack_factory)
