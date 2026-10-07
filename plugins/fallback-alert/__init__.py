"""fallback-alert — a one-time Slack alert whenever the model or account changes.

Why
    When Hermes falls back to another provider it shows a "⚠️ Model fallback: …" notice only in the
    session where it happened. Sessions on Slack see it in their thread, but CLI / TUI / cron
    sessions only show it on screen. And when a credential pool moves to its next account within
    the same provider (e.g. personal -> work subscription), nothing is shown anywhere.

How
    After every main-loop API call (`post_api_request` hook):
      1. Model/provider, per session — alert when the serving provider leaves the configured
         `model.provider`, and again when it comes back. Slack sessions are skipped (their thread
         already carries Hermes' own notice).
      2. Account, per provider — alert when the "active" credential in the serving provider's pool
         (lowest priority that is not exhausted/dead, read from <HERMES_HOME>/auth.json) changes.
         This is global state, so it alerts once per change regardless of platform.
    The first observation is a baseline and never alerts. Posting runs on a short-lived non-daemon
thread, so it doesn't block the turn but a one-shot process still waits for it (10 s timeout).

Config (<HERMES_HOME>/.env)
    SLACK_BOT_TOKEN, SLACK_HOME_CHANNEL   where alerts go (already set by `hermes gateway setup`)
    FALLBACK_ALERT_ACCOUNT_NAMES           optional, human labels for pool entries:
                                           `personal=Personal,anthropic-oauth-2=Work`
Disable: `hermes plugins disable fallback-alert`.
"""
import json
import logging
import os
import threading
import urllib.request

logger = logging.getLogger(__name__)

_last_provider: dict = {}   # session_id -> last serving provider
_last_account: dict = {}    # provider   -> last active pool label ("" = none available)
_lock = threading.Lock()


def _hermes_home() -> str:
    try:
        from hermes_constants import get_hermes_home
        return str(get_hermes_home())
    except Exception:
        return os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")


def _primary_provider() -> str:
    try:
        from hermes_cli.config import load_config_readonly
        return str(((load_config_readonly() or {}).get("model") or {}).get("provider") or "")
    except Exception:
        return ""


def parse_account_names(raw: str) -> dict:
    """`a=Name A,b=Name B` -> {"a": "Name A", "b": "Name B"}. (pure)"""
    out = {}
    for part in (raw or "").split(","):
        key, sep, val = part.partition("=")
        if sep and key.strip() and val.strip():
            out[key.strip()] = val.strip()
    return out


def active_account(entries: list) -> "str | None":
    """Label of the first usable pool entry by priority; None when the pool has fewer than two
    entries (nothing to switch between); "" when every entry is exhausted/dead. (pure)"""
    if not isinstance(entries, list) or len(entries) < 2:
        return None
    for e in sorted(entries, key=lambda e: e.get("priority", 0)):
        if e.get("last_status") not in ("exhausted", "dead"):
            return e.get("label") or str(e.get("id", ""))[:8]
    return ""


def decide(prev: "str | None", cur: str, primary: str) -> "str | None":
    """Model alert kind: 'fallback' | 'recover' | None. (pure)"""
    if prev is None or not cur or not primary or prev == cur:
        return None
    if cur != primary:
        return "fallback"
    if prev is not None and prev != primary:
        return "recover"
    return None


def _pool_entries(provider: str) -> list:
    try:
        with open(os.path.join(_hermes_home(), "auth.json"), encoding="utf-8") as f:
            return (json.load(f).get("credential_pool") or {}).get(provider) or []
    except Exception:
        return []


def _name(label: str) -> str:
    if not label:
        return "(no usable account)"
    return parse_account_names(os.environ.get("FALLBACK_ALERT_ACCOUNT_NAMES", "")).get(label, label)


def _post(text: str) -> None:
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    channel = os.environ.get("SLACK_HOME_CHANNEL", "")
    if not token or not channel:
        logger.warning("fallback-alert: SLACK_BOT_TOKEN / SLACK_HOME_CHANNEL missing; alert dropped")
        return
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": channel, "text": text, "unfurl_links": False}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"})
    try:
        res = json.load(urllib.request.urlopen(req, timeout=10))
        if not res.get("ok"):
            logger.warning("fallback-alert: Slack post failed: %s", res.get("error"))
    except Exception as exc:
        logger.warning("fallback-alert: Slack post error: %s", exc)


def _send(text: str) -> None:
    # Non-daemon: a one-shot CLI/cron process waits for the post (bounded by the 10 s timeout)
    # instead of dropping it when the interpreter exits.
    threading.Thread(target=_post, args=(text,), daemon=False, name="fallback-alert-post").start()


def _on_post_api_request(session_id="", platform="", model="", provider="", **_kw):
    try:
        plat = (platform or "").lower()
        where = f"{plat or 'cli'} session `{session_id}`"
        primary = _primary_provider()

        with _lock:
            prev = _last_provider.get(session_id)
            _last_provider[session_id] = provider
        kind = decide(prev, provider, primary)
        if kind and plat != "slack":
            if kind == "fallback":
                _send(f":warning: *Hermes model fallback* — observed provider change `{prev}` -> `{provider}` "
                      f"(configured primary `{primary}`); now on "
                      f"`{model}` via `{provider}`. ({where})")
            else:
                _send(f":white_check_mark: *Hermes back on primary* — `{model}` via `{provider}`. ({where})")
            logger.info("fallback-alert: model %s %s->%s (%s)", kind, prev, provider, session_id)

        acct = active_account(_pool_entries(provider))
        if acct is not None:
            with _lock:
                prev_acct = _last_account.get(provider)
                _last_account[provider] = acct
            if prev_acct is not None and prev_acct != acct:
                _send(f":arrows_counterclockwise: *Hermes account switch* — `{provider}`: "
                      f"{_name(prev_acct)} -> *{_name(acct)}* (seen in {where})")
                logger.info("fallback-alert: account %s %s->%s", provider, prev_acct, acct)
    except Exception as exc:  # an alert must never break a turn
        logger.warning("fallback-alert failed: %s", exc)
    return None


def register(ctx) -> None:
    ctx.register_hook("post_api_request", _on_post_api_request)
