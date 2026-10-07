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
import asyncio, json
from types import SimpleNamespace as NS
try:
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_sdk.web.async_slack_response import AsyncSlackResponse
except ImportError:
    print('SDK_UNAVAILABLE')
    raise SystemExit(0)
from hermes_cli.plugins import discover_plugins, get_plugin_manager
from hermes_cli.lifecycle import ainvoke_hook, invoke_hook
from gateway.config import PlatformConfig, Platform
from plugins.platforms.slack.adapter import SlackAdapter
from agent.delegation_context import delegated_child_context
from gateway.session_context import set_session_vars, clear_session_vars

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

async def turn(sid, model, text):
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
        await asyncio.to_thread(worker)
        await asyncio.sleep(0)  # overlap two sessions sharing one adapter/channel
        result = await adapter.send('C_OFFLINE', text)
        assert result.success, result
    finally:
        clear_session_vars(tokens)

async def main():
    await asyncio.gather(turn('session-a', 'gpt-6.1-sol', 'alpha'),
                         turn('session-b', 'claude-sonnet-5-5', 'beta'))
    names = {body['text']: body.get('username') for method, body in client.requests}
    assert names == {'alpha': 'Hermes-example (gpt-6.1-sol)',
                     'beta': 'Hermes-example (claude-sonnet-5-5)'}, names
    assert len(client.requests) == 2
    # No observed serving model: don't invent one from configured model.
    await turn('session-c', None, 'unknown')
    assert 'username' not in client.requests[-1][1]
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
    # Native streaming starts before a serving model is known: always base name.
    adapter.MAX_MESSAGE_LENGTH = 39000
    start = len(client.requests)
    await ainvoke_hook('pre_gateway_dispatch', event=NS(source=NS(platform=Platform.SLACK, chat_id='C_OFFLINE')))
    invoke_hook('pre_api_request', session_id='stream-session', platform='slack', turn_id='stream-turn')
    draft = await adapter.send_draft('C_OFFLINE', 1, 'native', metadata={'thread_id': '10.0'})
    assert draft.success, draft
    invoke_hook('post_api_request', session_id='stream-session', platform='slack', turn_id='stream-turn',
                response_model='gpt-6.1-sol', assistant_message=NS(content='native done'))
    final = await adapter.send('C_OFFLINE', 'native done', metadata={'thread_id': '10.0'})
    assert final.success, final
    native = client.requests[start:]
    assert native[0][0] == 'chat.startStream', native
    assert any(m == 'chat.stopStream' for m,b in native), native
    assert all('username' not in b for m,b in native), native
    await adapter.send('C_OFFLINE', 'native done')  # identical later system text must not reuse evidence
    assert 'username' not in client.requests[-1][1]
    print(json.dumps({'discovered': True, 'sdk_payloads': True, 'session_isolation': True,
                      'child_isolation': True, 'block_retry': True, 'chunks': len(chunks),
                      'update_unchanged': True, 'no_extra_normal_send_calls': True}))
asyncio.run(main())
'''
            result = subprocess.run([python, '-c', code], cwd=home, env=env,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            if 'SDK_UNAVAILABLE' in result.stdout:
                self.skipTest('real SDK requires slack-sdk, slack-bolt and aiohttp')
            proof = json.loads(result.stdout.splitlines()[-1])
            self.assertTrue(proof['sdk_payloads'])
            print('MODEL_DISPLAY_COMPATIBILITY_PROOF ' + json.dumps(proof))
