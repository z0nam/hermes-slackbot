"""Offline per-response name tests; no network, real SDK in compatibility mode."""
import asyncio
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class ModelDisplay(unittest.IsolatedAsyncioTestCase):
    def plugin(self):
        path = ROOT / 'plugins/slack-model-display/__init__.py'
        self.assertTrue(path.exists(), 'per-response display plugin is missing')
        spec = importlib.util.spec_from_file_location('model_display', path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        hooks, factories = {}, {}
        module.register(NS(get_config=lambda key, default='': {'base_name': 'Hermes-example'}.get(key, default),
                           register_hook=lambda n, f: hooks.update({n: f}),
                           register_platform_handler=lambda n, f: factories.update({n: f})))
        return module, hooks, factories

    async def harness(self):
        module, hooks, factories = self.plugin()
        guard = patch.dict('sys.modules', {'agent.delegation_context': NS(is_delegated_child_context=lambda: False)})
        guard.start()
        self.addCleanup(guard.stop)
        payloads = []
        class Adapter:
            _bot_display_name = 'Hermes-example'
            _team_bot_names = {}
            async def _call_with_block_fallback(self, client_fn, method, kwargs, verb):
                payloads.append((method, kwargs))
                return {'ts': '1.0'}
            async def _post_chunks(self, chat_id, team_id, content, formatted, thread_ts):
                return await self._call_with_block_fallback(None, 'chat_postMessage',
                    {'channel': chat_id, 'text': formatted, 'thread_ts': thread_ts}, 'send')
        adapter = Adapter()
        factories['slack'](None, adapter)
        event = NS(source=NS(platform=NS(value='slack'), chat_id='offline-channel'))
        await hooks['pre_gateway_dispatch'](event=event)
        return module, hooks, adapter, payloads, event

    async def test_actual_response_model_reaches_post_payload(self):
        module, hooks, adapter, payloads, event = await self.harness()
        await asyncio.to_thread(hooks['post_api_request'], session_id='session-a', platform='slack',
                               model='configured-not-serving', response_model='gpt-6.1-sol',
                               assistant_message=NS(content='hello', tool_calls=None))
        await adapter._post_chunks('offline-channel', '', 'hello', 'hello', '1.0')
        self.assertEqual(payloads, [('chat_postMessage', {'channel': 'offline-channel',
                         'text': 'hello', 'thread_ts': '1.0',
                         'username': 'Hermes-example (gpt-6.1-sol)'})])

    async def test_tool_call_content_is_not_a_response_name(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['post_api_request'](session_id='session-a', platform='slack',
            response_model='tool-model', assistant_message=NS(content='hello', tool_calls=[NS(id='offline')]))
        await adapter._post_chunks('offline-channel', '', 'hello', 'hello', None)
        self.assertNotIn('username', payloads[-1][1])

    async def test_new_request_invalidates_previous_response(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['post_api_request'](session_id='session-a', platform='slack', response_model='old-model',
                                 assistant_message=NS(content='hello'))
        self.assertIn('pre_api_request', hooks, 'request boundary hook is missing')
        hooks['pre_api_request'](session_id='session-a', platform='slack')
        await adapter._post_chunks('offline-channel', '', 'hello', 'hello', None)
        self.assertNotIn('username', payloads[-1][1])

    async def test_delegated_child_cannot_replace_parent_response(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['pre_api_request'](session_id='parent', platform='slack')
        hooks['post_api_request'](session_id='parent', platform='slack', response_model='parent-model',
                                 assistant_message=NS(content='hello'))
        with patch.dict('sys.modules', {'agent.delegation_context': NS(is_delegated_child_context=lambda: True)}):
            hooks['pre_api_request'](session_id='child', platform='slack')
            hooks['post_api_request'](session_id='child', platform='slack', response_model='child-model',
                                     assistant_message=NS(content='hello'))
        await adapter._post_chunks('offline-channel', '', 'hello', 'hello', None)
        self.assertEqual(payloads[-1][1].get('username'), 'Hermes-example (parent-model)')

    async def test_mismatched_session_cannot_supply_model(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['pre_api_request'](session_id='parent', platform='slack')
        hooks['post_api_request'](session_id='other', platform='slack', response_model='wrong-model',
                                 assistant_message=NS(content='hello'))
        await adapter._post_chunks('offline-channel', '', 'hello', 'hello', None)
        self.assertNotIn('username', payloads[-1][1])

    async def test_response_evidence_is_consumed_once(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['post_api_request'](session_id='parent', platform='slack', response_model='actual-model',
                                 assistant_message=NS(content='hello'))
        await adapter._post_chunks('offline-channel', '', 'hello', 'hello', None)
        await adapter._post_chunks('offline-channel', '', 'hello', 'hello', None)
        self.assertEqual(payloads[0][1]['username'], 'Hermes-example (actual-model)')
        self.assertNotIn('username', payloads[1][1])

    async def test_invalid_model_names_fail_to_base_name(self):
        module, hooks, adapter, payloads, event = await self.harness()
        for model in ['bad\nmodel', 'm' * 200, 'bad (label)', {'model': 'unknown'}]:
            hooks['post_api_request'](session_id='parent', platform='slack', response_model=model,
                                     assistant_message=NS(content='hello'))
            await adapter._post_chunks('offline-channel', '', 'hello', 'hello', None)
            self.assertNotIn('username', payloads[-1][1])

    async def test_gateway_trimmed_response_keeps_actual_model(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['post_api_request'](session_id='parent', platform='slack', response_model='actual-model',
                                 assistant_message=NS(content='hello\n'))
        await adapter._post_chunks('offline-channel', '', 'hello', 'hello', None)
        self.assertEqual(payloads[-1][1].get('username'), 'Hermes-example (actual-model)')

    async def test_missing_child_guard_disables_attribution(self):
        module, hooks, adapter, payloads, event = await self.harness()
        with patch.dict('sys.modules', {'agent.delegation_context': NS()}):
            hooks['post_api_request'](session_id='unknown', platform='slack', response_model='unknown-model',
                                     assistant_message=NS(content='hello'))
        await adapter._post_chunks('offline-channel', '', 'hello', 'hello', None)
        self.assertNotIn('username', payloads[-1][1])
