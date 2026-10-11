"""Opt-in final-answer Slack names. No profile changes or additional API calls."""
from contextvars import ContextVar
import re
import sys
from typing import Any

_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,159}\Z")

# Bind before gateway executor / bounded hook workers copy the context. Mutate
# the envelope, not the worker ContextVar; never cache a process-wide last model.
_turn: ContextVar[Any] = ContextVar('slack_model_display_turn', default=None)
_delivery: ContextVar[Any] = ContextVar('slack_model_display_delivery', default=None)
_name: ContextVar[Any] = ContextVar('slack_model_display_name', default=None)


async def _on_dispatch(event=None, **kwargs):
    source: Any = getattr(event, 'source', None)
    platform = getattr(getattr(source, 'platform', None), 'value', '')
    _turn.set({'chat_id': source.chat_id, 'scope_id': getattr(source, 'scope_id', None),
               'thread_id': getattr(source, 'thread_id', None),
               'message_id': getattr(event, 'message_id', None) or getattr(source, 'message_id', None),
               'response': None, 'final': None}
              if platform == 'slack' else None)


def _is_child():
    try:
        from agent.delegation_context import is_delegated_child_context
        return is_delegated_child_context()
    except ImportError:
        return True  # Without a child guard, attribution cannot be proven safe.


def _on_request(session_id='', platform='', turn_id='', **kwargs):
    turn = _turn.get()
    if turn is not None and platform == 'slack' and session_id and not _is_child():
        turn.update(response=None, final=None, session_id=session_id, turn_id=turn_id)


def _on_response(session_id='', platform='', response_model=None, assistant_message=None,
                 turn_id='', **kwargs):
    turn = _turn.get()
    if turn is None or platform != 'slack' or not session_id or _is_child():
        return
    if turn.get('session_id', session_id) != session_id or turn.get('turn_id', turn_id) != turn_id:
        return
    content = getattr(assistant_message, 'content', None)
    content = content.strip() if isinstance(content, str) else None
    if getattr(assistant_message, 'tool_calls', None):
        response_model = None
    turn['response'] = (session_id, content, response_model)


def _on_final(session_id='', platform='', assistant_response=None, turn_id='', **kwargs):
    turn = _turn.get()
    if (turn is None or platform != 'slack' or not session_id or _is_child()
            or turn.get('session_id') != session_id or turn.get('turn_id', '') != turn_id):
        return
    if not isinstance(assistant_response, str) or not assistant_response.strip():
        return
    text = assistant_response.strip()
    response = turn.get('response')
    model = response[2] if response and response[1] == text else None
    # Reuse the running gateway's exact sanitizer (redaction / terminal EOS),
    # never fuzzy-match or import its process entry point from a hook worker.
    variants = {text}
    sanitize = getattr(sys.modules.get('gateway.run'), '_sanitize_gateway_final_response', None)
    if callable(sanitize):
        clean = sanitize('slack', text)
        if isinstance(clean, str) and clean.strip():
            variants.add(clean.strip())
    turn['final'] = (frozenset(variants), model)


def _slack_factory(app, adapter, base_name=''):
    original: Any = getattr(adapter, '_post_chunks', None)
    call: Any = getattr(adapter, '_call_with_block_fallback', None)
    send: Any = getattr(adapter, 'send', None)
    if (not all(callable(f) for f in (original, call, send))
            or getattr(original, '_model_display_wrapped', False)):
        return

    async def post(chat_id, team_id, content, formatted, thread_ts):
        final = _delivery.get()
        name = None
        if final:
            model = final[1] if isinstance(final[1], str) and _MODEL.fullmatch(final[1]) else '모델 확인 불가'
            base = (base_name or getattr(adapter, '_team_bot_names', {}).get(team_id)
                    or getattr(adapter, '_bot_display_name', None) or 'Hermes')
            name = f'{base} ({model})'
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

    async def deliver(chat_id, content, reply_to=None, metadata=None):
        turn = _turn.get()
        final = turn.get('final') if turn and turn['chat_id'] == chat_id else None
        # notify alone also marks command replies. Require the finalized turn's
        # exact text as well, and never let reasoning/commentary consume it.
        eligible = (final and isinstance(content, str) and content.strip() in final[0]
                    and metadata and metadata.get('notify') is True
                    and not metadata.get('_interim_send') and not metadata.get('expect_edits'))
        if eligible and turn.get('scope_id'):
            resolve_team = getattr(adapter, '_metadata_team_id', None)
            eligible = callable(resolve_team) and resolve_team(metadata) == turn['scope_id']
        if eligible and turn.get('thread_id'):
            resolve_thread = getattr(adapter, '_resolve_thread_ts', None)
            # A synthetic ingress thread becomes a flat outbound reply when
            # reply_in_thread=false. Compare routes using the adapter's semantics,
            # but also require the raw identity: unrelated synthetic threads can
            # both resolve to None and must never share attribution.
            md = metadata or {}
            raw_thread = md.get('thread_id') or md.get('thread_ts') or reply_to
            eligible = (callable(resolve_thread) and raw_thread == turn['thread_id']
                        and resolve_thread(reply_to, metadata) == resolve_thread(
                            turn['message_id'], {'thread_id': turn['thread_id']}))
        token = _delivery.set(final if eligible else None)
        try:
            result = await send(chat_id, content, reply_to=reply_to, metadata=metadata)
            # Streams/ephemerals bypass _post_chunks. Successful delivery consumes
            # evidence there too; failed sends retain it for the existing retry.
            if eligible and getattr(result, 'success', False) and turn.get('final') is final:
                turn['final'] = None
                turn['response'] = None
            return result
        finally:
            _delivery.reset(token)

    adapter.send = deliver
    post._model_display_wrapped = True
    adapter._post_chunks = post
    adapter._call_with_block_fallback = decorate


def register(ctx):
    ctx.register_hook('pre_gateway_dispatch', _on_dispatch)
    ctx.register_hook('pre_api_request', _on_request)
    ctx.register_hook('post_api_request', _on_response)
    ctx.register_hook('post_llm_call', _on_final)
    base_name = ctx.get_config('base_name', '')
    ctx.register_platform_handler('slack', lambda app, adapter: _slack_factory(app, adapter, base_name))
