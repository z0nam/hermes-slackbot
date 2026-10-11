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
            send_success = True
            @staticmethod
            def _metadata_team_id(metadata):
                return (metadata or {}).get('slack_team_id', '')
            @staticmethod
            def _resolve_thread_ts(reply_to, metadata):
                return (metadata or {}).get('thread_id') or reply_to
            async def _call_with_block_fallback(self, client_fn, method, kwargs, verb):
                payloads.append((method, kwargs))
                return {'ts': '1.0'}
            async def send(self, chat_id, content, reply_to=None, metadata=None):
                await self._post_chunks(chat_id, '', content, content, reply_to)
                return NS(success=self.send_success, message_id='1.0')
            async def _post_chunks(self, chat_id, team_id, content, formatted, thread_ts):
                return await self._call_with_block_fallback(None, 'chat_postMessage',
                    {'channel': chat_id, 'text': formatted, 'thread_ts': thread_ts}, 'send')
        adapter = Adapter()
        factories['slack'](None, adapter)
        event = NS(source=NS(platform=NS(value='slack'), chat_id='offline-channel'))
        await hooks['pre_gateway_dispatch'](event=event)
        hooks['pre_api_request'](session_id='parent', platform='slack')
        return module, hooks, adapter, payloads, event

    async def final_send(self, hooks, adapter, text='hello', session_id='parent', reply_to=None):
        hooks['post_llm_call'](session_id=session_id, platform='slack', assistant_response=text)
        return await adapter.send('offline-channel', text, reply_to=reply_to, metadata={'notify': True})

    async def test_final_survives_identical_progress_after_response_hook(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['pre_api_request'](session_id='parent', platform='slack')
        hooks['post_api_request'](session_id='parent', platform='slack', response_model='actual-model',
                                 assistant_message=NS(content='hello'))
        # Intake relays thinking AFTER post_api_request, before finalization.
        await adapter.send('offline-channel', 'hello', metadata={'_interim_send': True})
        self.assertNotIn('username', payloads[-1][1])
        await adapter.send('offline-channel', 'hello')  # unmarked reasoning/status send
        self.assertNotIn('username', payloads[-1][1])
        hooks['post_llm_call'](session_id='parent', platform='slack', assistant_response='hello')
        await adapter.send('offline-channel', 'hello', metadata={'notify': True})
        self.assertEqual(payloads[-1][1].get('username'), 'Hermes-example (actual-model)')
        await adapter.send('offline-channel', 'hello', metadata={'notify': True})
        self.assertNotIn('username', payloads[-1][1])

    async def test_unknown_final_is_explicit_without_config_guess(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['pre_api_request'](session_id='parent', platform='slack')
        hooks['post_api_request'](session_id='parent', platform='slack', model='configured-not-observed',
                                 response_model=None, assistant_message=NS(content='hello'))
        hooks['post_llm_call'](session_id='parent', platform='slack', model='configured-not-observed',
                               assistant_response='hello')
        await adapter.send('offline-channel', 'hello', metadata={'notify': True})
        self.assertEqual(payloads[-1][1].get('username'), 'Hermes-example (모델 확인 불가)')

    async def test_scope_and_thread_mismatch_do_not_consume_final(self):
        module, hooks, adapter, payloads, event = await self.harness()
        event.source.scope_id = 'offline-team'
        event.source.thread_id = '10.0'
        await hooks['pre_gateway_dispatch'](event=event)
        hooks['pre_api_request'](session_id='parent', platform='slack')
        hooks['post_api_request'](session_id='parent', platform='slack', response_model='actual-model',
                                 assistant_message=NS(content='hello'))
        hooks['post_llm_call'](session_id='parent', platform='slack', assistant_response='hello')
        await adapter.send('offline-channel', 'hello', metadata={
            'notify': True, 'slack_team_id': 'other-team', 'thread_id': '10.0'})
        self.assertNotIn('username', payloads[-1][1])
        await adapter.send('offline-channel', 'hello', metadata={
            'notify': True, 'slack_team_id': 'offline-team', 'thread_id': '20.0'})
        self.assertNotIn('username', payloads[-1][1])
        await adapter.send('offline-channel', 'hello', metadata={
            'notify': True, 'slack_team_id': 'offline-team', 'thread_id': '10.0'})
        self.assertEqual(payloads[-1][1].get('username'), 'Hermes-example (actual-model)')

    async def test_final_authority_does_not_relax_content_or_delivery_kind(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['post_api_request'](session_id='parent', platform='slack', response_model='actual-model',
                                 assistant_message=NS(content='hello'))
        hooks['post_llm_call'](session_id='parent', platform='slack', assistant_response='hello')
        for text, metadata in [('hello', None), ('hello', {'_interim_send': True, 'notify': True}),
                               ('hello', {'expect_edits': True, 'notify': True}),
                               ('prefix hello', {'notify': True}), ('hel', {'notify': True})]:
            await adapter.send('offline-channel', text, metadata=metadata)
            self.assertNotIn('username', payloads[-1][1])
        await adapter.send('offline-channel', 'hello', metadata={'notify': True})
        self.assertEqual(payloads[-1][1].get('username'), 'Hermes-example (actual-model)')

    async def test_transformed_final_without_exact_provider_evidence_is_unknown(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['post_api_request'](session_id='parent', platform='slack', response_model='actual-model',
                                 assistant_message=NS(content='original'))
        await self.final_send(hooks, adapter, text='rewritten final')
        self.assertEqual(payloads[-1][1].get('username'), 'Hermes-example (모델 확인 불가)')

    async def test_child_finalization_cannot_replace_parent_final(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['post_api_request'](session_id='parent', platform='slack', response_model='parent-model',
                                 assistant_message=NS(content='hello'))
        hooks['post_llm_call'](session_id='parent', platform='slack', assistant_response='hello')
        with patch.dict('sys.modules', {'agent.delegation_context': NS(is_delegated_child_context=lambda: True)}):
            hooks['post_llm_call'](session_id='parent', platform='slack', assistant_response='wrong final')
        await adapter.send('offline-channel', 'hello', metadata={'notify': True})
        self.assertEqual(payloads[-1][1].get('username'), 'Hermes-example (parent-model)')

    async def test_stale_turn_finalization_is_ignored(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['pre_api_request'](session_id='parent', platform='slack', turn_id='new')
        hooks['post_api_request'](session_id='parent', platform='slack', turn_id='old',
                                 response_model='wrong-model', assistant_message=NS(content='hello'))
        hooks['post_llm_call'](session_id='parent', platform='slack', turn_id='old', assistant_response='hello')
        await adapter.send('offline-channel', 'hello', metadata={'notify': True})
        self.assertNotIn('username', payloads[-1][1])
        hooks['post_llm_call'](session_id='parent', platform='slack', turn_id='new', assistant_response='hello')
        await adapter.send('offline-channel', 'hello', metadata={'notify': True})
        self.assertEqual(payloads[-1][1].get('username'), 'Hermes-example (모델 확인 불가)')

    async def test_actual_response_model_reaches_post_payload(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['pre_api_request'](session_id='session-a', platform='slack')
        await asyncio.to_thread(hooks['post_api_request'], session_id='session-a', platform='slack',
                               model='configured-not-serving', response_model='gpt-6.1-sol',
                               assistant_message=NS(content='hello', tool_calls=None))
        await self.final_send(hooks, adapter, session_id='session-a', reply_to='1.0')
        self.assertEqual(payloads, [('chat_postMessage', {'channel': 'offline-channel',
                         'text': 'hello', 'thread_ts': '1.0',
                         'username': 'Hermes-example (gpt-6.1-sol)'})])

    async def test_tool_call_content_is_not_a_response_name(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['post_api_request'](session_id='session-a', platform='slack',
            response_model='tool-model', assistant_message=NS(content='hello', tool_calls=[NS(id='offline')]))
        await adapter.send('offline-channel', 'hello', metadata={'notify': True})
        self.assertNotIn('username', payloads[-1][1])

    async def test_new_request_invalidates_previous_response(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['post_api_request'](session_id='session-a', platform='slack', response_model='old-model',
                                 assistant_message=NS(content='hello'))
        self.assertIn('pre_api_request', hooks, 'request boundary hook is missing')
        hooks['pre_api_request'](session_id='session-a', platform='slack')
        await adapter.send('offline-channel', 'hello', metadata={'notify': True})
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
        await self.final_send(hooks, adapter)
        self.assertEqual(payloads[-1][1].get('username'), 'Hermes-example (parent-model)')

    async def test_mismatched_session_cannot_supply_model(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['pre_api_request'](session_id='parent', platform='slack')
        hooks['post_api_request'](session_id='other', platform='slack', response_model='wrong-model',
                                 assistant_message=NS(content='hello'))
        await adapter.send('offline-channel', 'hello', metadata={'notify': True})
        self.assertNotIn('username', payloads[-1][1])

    async def test_response_evidence_is_consumed_once(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['post_api_request'](session_id='parent', platform='slack', response_model='actual-model',
                                 assistant_message=NS(content='hello'))
        await self.final_send(hooks, adapter)
        await adapter.send('offline-channel', 'hello', metadata={'notify': True})
        self.assertEqual(payloads[0][1]['username'], 'Hermes-example (actual-model)')
        self.assertNotIn('username', payloads[1][1])

    async def test_failed_delivery_keeps_final_for_existing_retry(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['post_api_request'](session_id='parent', platform='slack', response_model='actual-model',
                                 assistant_message=NS(content='hello'))
        adapter.send_success = False
        result = await self.final_send(hooks, adapter)
        self.assertFalse(result.success)
        adapter.send_success = True
        result = await adapter.send('offline-channel', 'hello', metadata={'notify': True})
        self.assertTrue(result.success)
        self.assertEqual([body.get('username') for _, body in payloads],
                         ['Hermes-example (actual-model)', 'Hermes-example (actual-model)'])
        await adapter.send('offline-channel', 'hello', metadata={'notify': True})
        self.assertNotIn('username', payloads[-1][1])

    async def test_invalid_model_names_are_explicitly_unknown(self):
        module, hooks, adapter, payloads, event = await self.harness()
        for model in ['bad\nmodel', 'm' * 200, 'bad (label)', {'model': 'unknown'}]:
            hooks['pre_api_request'](session_id='parent', platform='slack')
            hooks['post_api_request'](session_id='parent', platform='slack', response_model=model,
                                     assistant_message=NS(content='hello'))
            await self.final_send(hooks, adapter)
            self.assertEqual(payloads[-1][1].get('username'), 'Hermes-example (모델 확인 불가)')

    async def test_gateway_trimmed_response_keeps_actual_model(self):
        module, hooks, adapter, payloads, event = await self.harness()
        hooks['post_api_request'](session_id='parent', platform='slack', response_model='actual-model',
                                 assistant_message=NS(content='hello\n'))
        await self.final_send(hooks, adapter)
        self.assertEqual(payloads[-1][1].get('username'), 'Hermes-example (actual-model)')

    async def test_missing_child_guard_disables_attribution(self):
        module, hooks, adapter, payloads, event = await self.harness()
        with patch.dict('sys.modules', {'agent.delegation_context': NS()}):
            hooks['post_api_request'](session_id='unknown', platform='slack', response_model='unknown-model',
                                     assistant_message=NS(content='hello'))
        await adapter.send('offline-channel', 'hello', metadata={'notify': True})
        self.assertNotIn('username', payloads[-1][1])
