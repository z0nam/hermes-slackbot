"""Opt-in per-response Slack names. No profile changes or additional API calls."""
from contextvars import ContextVar
import re

_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,159}\Z")

# Bind a new mutable envelope on ingress, before gateway copies the context to its
# agent executor / bounded hook workers. Mutations flow back; ContextVar.set in
# a worker would NOT. No process-wide last-model or session cache.
_turn = ContextVar('slack_model_display_turn', default=None)
_name = ContextVar('slack_model_display_name', default=None)


async def _on_dispatch(event=None, **kwargs):
    source = getattr(event, 'source', None)
    platform = getattr(getattr(source, 'platform', None), 'value', '')
    _turn.set({'chat_id': source.chat_id, 'response': None} if platform == 'slack' else None)


def _is_child():
    try:
        from agent.delegation_context import is_delegated_child_context
        return is_delegated_child_context()
    except ImportError:
        return True  # Without a child guard, attribution cannot be proven safe.


def _on_request(session_id='', platform='', **kwargs):
    turn = _turn.get()
    if turn is not None and platform == 'slack' and session_id and not _is_child():
        turn['response'] = None
        turn['session_id'] = session_id


def _on_response(session_id='', platform='', response_model=None, assistant_message=None, **kwargs):
    turn = _turn.get()
    if turn is None or platform != 'slack' or not session_id or _is_child():
        return
    if turn.get('session_id', session_id) != session_id:
        return
    content = getattr(assistant_message, 'content', None)
    content = content.strip() if isinstance(content, str) else None
    if getattr(assistant_message, 'tool_calls', None):
        response_model = None
    turn['response'] = (session_id, content, response_model)


def _slack_factory(app, adapter, base_name=''):
    original = getattr(adapter, '_post_chunks', None)
    call = getattr(adapter, '_call_with_block_fallback', None)
    if not callable(original) or not callable(call) or getattr(original, '_model_display_wrapped', False):
        return

    async def post(chat_id, team_id, content, formatted, thread_ts):
        turn = _turn.get()
        response = turn.get('response') if turn and turn['chat_id'] == chat_id else None
        name = None
        if (response and response[1] and isinstance(content, str) and response[1] == content.strip()
                and isinstance(response[2], str) and _MODEL.fullmatch(response[2])):
            base = (base_name or getattr(adapter, '_team_bot_names', {}).get(team_id)
                    or getattr(adapter, '_bot_display_name', None))
            if base:
                name = f'{base} ({response[2]})'
                turn['response'] = None  # evidence belongs to one delivery, not later notices
        token = _name.set(name)
        try:
            return await original(chat_id, team_id, content, formatted, thread_ts)
        finally:
            _name.reset(token)

    async def decorate(client_fn, method, kwargs, verb):
        name = _name.get()
        if method == 'chat_postMessage' and name:
            kwargs = {**kwargs, 'username': name}
        return await call(client_fn, method, kwargs, verb)

    send = getattr(adapter, 'send', None)
    if callable(send):
        async def deliver(chat_id, content, reply_to=None, metadata=None):
            turn = _turn.get()
            response = turn.get('response') if turn and turn['chat_id'] == chat_id else None
            try:
                return await send(chat_id, content, reply_to=reply_to, metadata=metadata)
            finally:
                # Streams/ephemerals may bypass _post_chunks entirely. A completed
                # delivery must not leave its evidence available to later notices.
                if (response and isinstance(content, str) and response[1] == content.strip()
                        and turn.get('response') is response):
                    turn['response'] = None
        adapter.send = deliver

    post._model_display_wrapped = True
    adapter._post_chunks = post
    adapter._call_with_block_fallback = decorate


def register(ctx):
    ctx.register_hook('pre_gateway_dispatch', _on_dispatch)
    ctx.register_hook('pre_api_request', _on_request)
    ctx.register_hook('post_api_request', _on_response)
    base_name = ctx.get_config('base_name', '')
    ctx.register_platform_handler('slack', lambda app, adapter: _slack_factory(app, adapter, base_name))
