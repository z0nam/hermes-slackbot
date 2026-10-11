"""Hermes lifecycle + real Slack SDK payloads; transport replaced before HTTP."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('HERMES_AGENT_DIR'), 'needs a Hermes checkout')
class ModelDisplayCompatibility(unittest.TestCase):
    def test_discovery_worker_context_and_sdk_payloads(self):
        self.assertTrue((ROOT / 'plugins/slack-model-display/plugin.yaml').exists(),
                        'discoverable model display manifest is missing')
        source = Path(os.environ['HERMES_AGENT_DIR'])
        python = os.environ.get('HERMES_PYTHON', str(source / 'venv/bin/python'))

        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            home = Path(directory)
            shutil.copytree(ROOT / 'plugins/slack-model-display', home / 'plugins/slack-model-display')
            (home / 'config.yaml').write_text(json.dumps({'plugins': {
                'enabled': ['slack-model-display'], 'entries': {'slack-model-display': {
                    'settings': {'base_name': 'Hermes-example'}}}}}))
            env = {'PATH': os.environ['PATH'], 'HOME': str(home), 'HERMES_HOME': str(home),
                   'PYTHONPATH': str(source), 'TMPDIR': str(home),
                   'HERMES_ENABLE_PROJECT_PLUGINS': 'false'}
            code = '''
import asyncio, json, logging
from types import SimpleNamespace as NS
try:
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_sdk.web.async_slack_response import AsyncSlackResponse
except ImportError as exc:
    print('SDK_UNAVAILABLE: ' + str(exc))
    raise SystemExit(0)
from hermes_cli.plugins import discover_plugins, get_plugin_manager
from hermes_cli.lifecycle import ainvoke_hook, invoke_hook
from gateway.config import PlatformConfig, Platform
from gateway.platforms.event import MessageEvent
from gateway.platforms.base import _reply_anchor_for_event
from plugins.platforms.slack.adapter import SlackAdapter
from agent.delegation_context import delegated_child_context
from gateway.session_context import set_session_vars, clear_session_vars
from agent.turn_finalizer import _apply_output_hooks
from agent.turn_response_intake import normalize_model_response
from gateway.stream_consumer import GatewayStreamConsumer
# Import runtime helpers without executing entry-point dependency adoption /
# interpreter relaunch. The tested hooks, gateway helpers and SDK remain real.
from unittest.mock import patch
with patch('hermes_cli.venv_sync.prepare_launch', return_value=None), \
     patch('hermes_cli._early_recovery.recover_if_needed', return_value=None), \
     patch('pm.environments.activate_dependencies', return_value=None):
    from gateway.run import _sanitize_gateway_final_response

class OfflineSDK(AsyncWebClient):
    def __init__(self):
        super().__init__(token='offline-placeholder')
        self.requests = []
        self.reject_blocks = False
    async def _send(self, http_verb, api_url, req_args):
        # Execute actual SDK method/API argument building, intercept only HTTP.
        body = req_args.get('json') or req_args.get('data') or {}
        self.requests.append((api_url.rsplit('/', 1)[-1], dict(body)))
        data = {'ok': True, 'ts': str(len(self.requests)) + '.0'}
        if self.reject_blocks and body.get('blocks'):
            data = {'ok': False, 'error': 'invalid_blocks'}
            self.reject_blocks = False
        result = AsyncSlackResponse(client=self, http_verb=http_verb, api_url=api_url,
            req_args=req_args, data=data, headers={}, status_code=200)
        return result.validate()

discover_plugins()
pm = get_plugin_manager()
assert [name for _, name in pm.get_platform_handler_factories('slack')] == ['slack-model-display']
client = OfflineSDK()
adapter = SlackAdapter(PlatformConfig(enabled=True, token='offline-placeholder'))
adapter._app = NS(client=client)
adapter._bot_display_name = 'profile-name'
adapter._wire_plugin_handlers(adapter._app)
wrapped = adapter._post_chunks
adapter._wire_plugin_handlers(adapter._app)
assert wrapped is adapter._post_chunks
assert not getattr(SlackAdapter._post_chunks, '_model_display_wrapped', False)

async def turn(sid, model, text, delivery_text=None):
    event = NS(source=NS(platform=Platform.SLACK, chat_id='C_OFFLINE'))
    await ainvoke_hook('pre_gateway_dispatch', event=event)
    tokens = set_session_vars(platform='slack', chat_id='C_OFFLINE', session_id=sid)
    try:
        def worker():
            invoke_hook('pre_api_request', session_id=sid, platform='slack', turn_id=sid)
            invoke_hook('post_api_request', session_id=sid, platform='slack', turn_id=sid,
                        model='configured-not-serving', response_model=model,
                        assistant_message=NS(content=text, tool_calls=None))
            with delegated_child_context('child'):
                invoke_hook('pre_api_request', session_id='child', platform='slack', turn_id='child-'+sid)
                invoke_hook('post_api_request', session_id='child', platform='slack', turn_id='child-'+sid,
                            response_model='wrong-child-model', assistant_message=NS(content=text))
            # Exercise Hermes' actual output-finalization dispatch, not just our callback.
            _apply_output_hooks(NS(session_id=sid, model='configured-not-serving'), text,
                logging.getLogger('offline'), platform='slack', effective_task_id=sid,
                turn_id=sid, original_user_message='offline input', messages=[])
        await asyncio.to_thread(worker)
        await asyncio.sleep(0)  # overlap two sessions sharing one adapter/channel
        result = await adapter.send('C_OFFLINE', text if delivery_text is None else delivery_text,
                                    metadata={'notify': True})
        assert result.success, result
    finally:
        clear_session_vars(tokens)

async def scoped_routes():
    cases = 0
    for reply_in_thread in (False, True):
        adapter.config.extra['reply_in_thread'] = reply_in_thread
        for existing_thread in (False, True):
            # Slack ingress uses the message's own ts as a synthetic top-level
            # thread identity, or the real parent ts for a threaded message.
            root = '10.0'
            message_id = '11.0' if existing_thread else root
            source = adapter.build_source(chat_id='C_OFFLINE', chat_type='group',
                user_id='U_OFFLINE', scope_id='T_OFFLINE', thread_id=root,
                message_id=message_id)
            event = MessageEvent(text='offline input', source=source, message_id=message_id)
            anchor = _reply_anchor_for_event(event)
            assert anchor == message_id
            await ainvoke_hook('pre_gateway_dispatch', event=event)
            sid = 'route-' + str(reply_in_thread) + '-' + str(existing_thread)
            invoke_hook('pre_api_request', session_id=sid, platform='slack', turn_id=sid)
            invoke_hook('post_api_request', session_id=sid, platform='slack', turn_id=sid,
                response_model='provider/route-model', assistant_message=NS(content='route final'))
            _apply_output_hooks(NS(session_id=sid, model='configured-not-serving'), 'route final',
                logging.getLogger('offline'), platform='slack', effective_task_id=sid,
                turn_id=sid, original_user_message=event.text, messages=[])
            # The gateway stamps both workspace aliases, ingress thread and message id.
            metadata = {'notify': True, 'scope_id': source.scope_id,
                'slack_team_id': source.scope_id, 'thread_id': source.thread_id,
                'message_id': message_id}
            wrong_workspace = {**metadata, 'scope_id': 'T_OTHER', 'slack_team_id': 'T_OTHER'}
            wrong_thread = {**metadata, 'thread_id': '20.0'}
            wrong_synthetic = {**metadata, 'thread_id': '20.0', 'message_id': '20.0'}
            rejected = [(anchor, wrong_workspace), (anchor, wrong_thread),
                        ('20.0', wrong_synthetic)]
            if not reply_in_thread:
                # Correct raw root, wrong reply anchor flips real vs flat routing.
                rejected.append((root if existing_thread else '11.0', metadata))
            for wrong_anchor, wrong_metadata in rejected:
                start = len(client.requests)
                result = await adapter.send('C_OFFLINE', 'route final',
                    reply_to=wrong_anchor, metadata=wrong_metadata)
                assert result.success, result
                posts = [body for method, body in client.requests[start:] if method == 'chat.postMessage']
                assert len(posts) == 1, client.requests[start:]
                assert 'username' not in posts[0], (sid, posts)
            start = len(client.requests)
            result = await adapter.send('C_OFFLINE', 'route final', reply_to=anchor, metadata=metadata)
            assert result.success, result
            posts = [body for method, body in client.requests[start:] if method == 'chat.postMessage']
            assert len(posts) == 1, client.requests[start:]
            body = posts[0]
            expected_thread = root if reply_in_thread or existing_thread else None
            assert body.get('thread_ts') == expected_thread, (sid, body)
            assert body.get('username') == 'Hermes-example (provider/route-model)', (sid, body)
            # Rejected sends must preserve evidence; the valid final alone consumes it.
            start = len(client.requests)
            await adapter.send('C_OFFLINE', 'route final', reply_to=anchor, metadata=metadata)
            posts = [body for method, body in client.requests[start:] if method == 'chat.postMessage']
            assert len(posts) == 1 and 'username' not in posts[0], (sid, posts)
            cases += 1
    adapter.config.extra.pop('reply_in_thread')
    client.requests.clear()
    return cases

async def main():
    route_cases = await scoped_routes()
    # Actual intake order: post_api_request -> reasoning.available callback ->
    # consumer commentary / status send -> actual output finalization -> final.
    await ainvoke_hook('pre_gateway_dispatch', event=NS(source=NS(platform=Platform.SLACK, chat_id='C_OFFLINE')))
    loop = asyncio.get_running_loop()
    consumer = GatewayStreamConsumer(adapter, 'C_OFFLINE')
    def ordered_worker():
        invoke_hook('pre_api_request', session_id='ordered', platform='slack', turn_id='ordered')
        def progress(*args):
            assert args[0] == 'reasoning.available', args
            assert asyncio.run_coroutine_threadsafe(consumer._send_commentary(args[2]), loop).result(5)
            asyncio.run_coroutine_threadsafe(adapter.send('C_OFFLINE', args[2]), loop).result(5)
        message = NS(content='ordered final', tool_calls=None, finish_reason='stop')
        agent = NS(session_id='ordered', platform='slack', model='configured-not-serving',
            provider='offline', base_url='', api_mode='chat_completions', quiet_mode=True,
            tool_progress_callback=progress, _get_transport=lambda: NS(normalize_response=lambda r: message),
            _api_response_payload_for_hook=lambda *a, **k: {},
            _usage_summary_for_api_request_hook=lambda r: {})
        verdict = normalize_model_response(agent, response=NS(model='provider/ordered-id'),
            messages=[], api_messages=[], conversation_history=[], api_call_count=1,
            api_duration=1, api_start_time=1, api_request_id='ordered-request',
            effective_task_id='ordered', turn_id='ordered')
        assert verdict.action == 'fallthrough', verdict
        _apply_output_hooks(agent, message.content, logging.getLogger('offline'), platform='slack',
            effective_task_id='ordered', turn_id='ordered', original_user_message='offline input', messages=[])
    await asyncio.to_thread(ordered_worker)
    result = await adapter.send('C_OFFLINE', 'ordered final', metadata={'notify': True})
    assert result.success, result
    assert len(client.requests) == 3, client.requests
    assert all('username' not in body for _, body in client.requests[:2]), client.requests
    assert client.requests[-1][1].get('username') == 'Hermes-example (provider/ordered-id)', client.requests[-1]
    client.requests.clear()
    await asyncio.gather(turn('session-a', 'gpt-6.1-sol', 'alpha'),
                         turn('session-b', 'claude-sonnet-5-5', 'beta'))
    names = {body['text']: body.get('username') for method, body in client.requests}
    assert names == {'alpha': 'Hermes-example (gpt-6.1-sol)',
                     'beta': 'Hermes-example (claude-sonnet-5-5)'}, names
    assert len(client.requests) == 2
    # No observed serving model: explicit unknown, never configured-model guessing.
    await turn('session-c', None, 'unknown')
    assert client.requests[-1][1].get('username') == 'Hermes-example (모델 확인 불가)'
    await adapter.send('C_OFFLINE', 'system notice')
    assert 'username' not in client.requests[-1][1]
    # Slack update has no username support; never add the parameter.
    result = await adapter.edit_message('C_OFFLINE', '1.0', 'edited')
    assert result.success, result
    assert client.requests[-1][0] == 'chat.update'
    assert 'username' not in client.requests[-1][1]
    # Actual adapter block-rejection retry keeps username without new plugin calls.
    client.reject_blocks = True
    adapter.config.extra['rich_blocks'] = True
    await turn('session-d', 'gpt-6.1-sol', '**bold**')
    final = client.requests[-2:]
    assert all(b.get('username') == 'Hermes-example (gpt-6.1-sol)' for m,b in final), final
    assert final[0][1].get('blocks') and 'blocks' not in final[1][1], final
    # Actual adapter multi-chunk path preserves the same response name per chunk.
    adapter.MAX_MESSAGE_LENGTH = 12
    start = len(client.requests)
    await turn('session-e', 'claude-sonnet-5-5', 'word ' * 10)
    chunks = client.requests[start:]
    assert len(chunks) > 1
    assert all(b.get('username') == 'Hermes-example (claude-sonnet-5-5)' for m,b in chunks)
    # Gateway terminal-sentinel sanitization is a specific supported rewrite,
    # not a fuzzy or substring content match.
    adapter.MAX_MESSAGE_LENGTH = 39000
    raw = 'sanitized final<|eos|>'
    clean = _sanitize_gateway_final_response(Platform.SLACK, raw)
    assert clean == 'sanitized final', clean
    await turn('sanitized-session', 'provider/exact-id', raw, delivery_text=clean)
    assert client.requests[-1][1].get('username') == 'Hermes-example (provider/exact-id)', client.requests[-1]
    # Native streaming starts before a serving model is known: always base name.
    adapter.MAX_MESSAGE_LENGTH = 39000
    start = len(client.requests)
    await ainvoke_hook('pre_gateway_dispatch', event=NS(source=NS(platform=Platform.SLACK, chat_id='C_OFFLINE')))
    invoke_hook('pre_api_request', session_id='stream-session', platform='slack', turn_id='stream-turn')
    draft = await adapter.send_draft('C_OFFLINE', 1, 'native', metadata={'thread_id': '10.0'})
    assert draft.success, draft
    invoke_hook('post_api_request', session_id='stream-session', platform='slack', turn_id='stream-turn',
                response_model='gpt-6.1-sol', assistant_message=NS(content='native done'))
    _apply_output_hooks(NS(session_id='stream-session', model='configured-not-serving'), 'native done',
        logging.getLogger('offline'), platform='slack', effective_task_id='stream-session',
        turn_id='stream-turn', original_user_message='offline input', messages=[])
    final = await adapter.send('C_OFFLINE', 'native done', metadata={'thread_id': '10.0', 'notify': True})
    assert final.success, final
    native = client.requests[start:]
    assert native[0][0] == 'chat.startStream', native
    assert any(m == 'chat.stopStream' for m,b in native), native
    assert all('username' not in b for m,b in native), native
    await adapter.send('C_OFFLINE', 'native done', metadata={'notify': True})  # must not reuse evidence
    assert 'username' not in client.requests[-1][1]
    print(json.dumps({'discovered': True, 'sdk_payloads': True, 'session_isolation': True,
                      'real_intake_callback_order': True, 'gateway_sanitization': True,
                      'scoped_reply_route_cases': route_cases,
                      'child_isolation': True, 'block_retry': True, 'chunks': len(chunks),
                      'update_unchanged': True, 'no_extra_normal_send_calls': True}))
asyncio.run(main())
'''
            result = subprocess.run([python, '-c', code], cwd=home, env=env,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            if 'SDK_UNAVAILABLE' in result.stdout:
                self.skipTest(result.stdout.strip())
            proof = json.loads(result.stdout.splitlines()[-1])
            self.assertTrue(proof['sdk_payloads'])
            print('MODEL_DISPLAY_COMPATIBILITY_PROOF ' + json.dumps(proof))
