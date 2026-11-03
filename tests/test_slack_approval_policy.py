"""Real registered handlers; fake service and consent, no Slack/network access."""
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
MISSING = object()


class ApprovalPolicy(unittest.TestCase):
    def handler(self, policy: object = 'explicit_request'):
        path = ROOT / 'plugins/slack-tools/__init__.py'
        spec = importlib.util.spec_from_file_location('approval_policy_plugin', path,
                                                    submodule_search_locations=[str(path.parent)])
        assert spec and spec.loader
        plugin = importlib.util.module_from_spec(spec)
        self.addCleanup(sys.modules.pop, spec.name, None)
        sys.modules[spec.name] = plugin
        spec.loader.exec_module(plugin)
        self.plugin = plugin
        tools = {}

        class Context:
            def get_config(_, key, default=None):
                return {'approval_policy': policy}.get(key, default) if policy is not MISSING else default

            def register_tool(_, **kw):
                tools[kw['name']] = kw

        plugin.register(Context())
        self.tool = tools['sapi_slack_write']
        return self.tool['handler']

    def invoke(self, action='post', quote: object = 'Post "hello" to the selected channel.',
               policy: object = 'explicit_request', include_quote=True):
        handler = self.handler(policy)
        args = {'action': action, 'text': 'hello', 'channel': 'C0123456789'}
        if action in ('send_dm', 'open_dm'):
            args = {'action': action, 'user': 'U0123456789'}
            if action == 'send_dm':
                args['text'] = 'hello'
        if action in ('update', 'delete'):
            args['ts'] = '1760000000.000001'
        if action == 'delete':
            args.pop('text')
        if include_quote:
            args['explicit_user_request'] = quote
        before = dict(args)
        fake = Mock()

        def write(**values):
            # This interface deliberately mirrors the service signature: no quote leaks.
            self.assertNotIn('explicit_user_request', values)
            approval = values.pop('approve')
            self.assertTrue(approval(json.dumps(values)))
            return {'verified': True}

        fake.write.side_effect = write
        gate = ModuleType('tools.approval_prompt')
        prompt = Mock(return_value='accept')
        setattr(gate, 'request_elicitation_consent', prompt)
        with patch.object(self.plugin, 'SlackService', return_value=fake), patch.dict(
                sys.modules, {'tools.approval_prompt': gate}):
            out = json.loads(handler(args))
        self.assertEqual(args, before, 'handler must not mutate caller arguments')
        return out, prompt, fake

    def test_opt_in_post_skips_redundant_prompt(self):
        out, prompt, fake = self.invoke()
        self.assertTrue(out['success'], out)
        prompt.assert_not_called()
        fake.write.assert_called_once()


    def test_real_service_validates_verifies_and_never_retries_with_opt_in(self):
        # Exercise the production service using the existing offline executable fixture.
        import test_slack_tools
        fixture = test_slack_tools.SlackTools(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        handler = self.handler()
        gate = ModuleType('tools.approval_prompt')
        prompt = Mock(side_effect=AssertionError('explicit send must not prompt'))
        setattr(gate, 'request_elicitation_consent', prompt)
        message = {'ts': '1760000000.000001', 'text': 'hello', 'user': 'U0123456789'}
        info = {'id': 'D0123456789', 'is_im': True, 'user': 'U9876543210'}
        post_args = {'action': 'post', 'channel': 'C0123456789', 'text': 'hello',
                     'explicit_user_request': 'Post hello to the selected channel now.'}
        cases = [
            (post_args, [{'ok': True, 'channel': 'C0123456789', 'ts': message['ts']},
                         {'ok': True, 'messages': [message]}], True, ['chat.postMessage', 'conversations.history']),
            (dict(post_args, thread_ts=message['ts']),
             [{'ok': True, 'channel': 'C0123456789', 'ts': message['ts']},
              {'ok': True, 'messages': [message]}], True, ['chat.postMessage', 'conversations.replies']),
            ({'action': 'send_dm', 'user': info['user'], 'text': 'hello',
              'explicit_user_request': 'Send hello to the selected user now.'},
             [{'ok': True, 'user_id': message['user']}, {'ok': True, 'channel': info},
              {'ok': True, 'channel': info['id'], 'ts': message['ts']},
              {'ok': True, 'channel': dict(info, latest=message)}], True,
             ['auth.test', 'conversations.open', 'chat.postMessage', 'conversations.open']),
            (dict(post_args, text=' '), [], False, []),
            (dict(post_args, channel='not-an-id'), [], False, []),
            (post_args, [{'ok': True, 'channel': 'C0123456789', 'ts': message['ts']},
                         {'ok': True, 'messages': []}], False, ['chat.postMessage', 'conversations.history']),
        ]
        for args, responses, success, methods in cases:
            with self.subTest(args=args, success=success):
                fixture.log.unlink(missing_ok=True)
                client = fixture.client(responses)
                with patch.object(self.plugin, 'SlackService', return_value=client), patch.dict(
                        sys.modules, {'tools.approval_prompt': gate}):
                    out = json.loads(handler(args))
                self.assertEqual(out['success'], success, out)
                calls = [json.loads(line)[0] for line in fixture.log.read_text().splitlines()] if fixture.log.exists() else []
                self.assertEqual(calls, methods)
        prompt.assert_not_called()

    def test_opt_in_is_not_reused_for_a_subsequent_unquoted_send(self):
        handler = self.handler()
        gate = ModuleType('tools.approval_prompt')
        prompt = Mock(return_value='decline')
        setattr(gate, 'request_elicitation_consent', prompt)
        fake = Mock()

        def write(*, approve, **values):
            if approve(json.dumps(values)):
                return {'verified': True}

        fake.write.side_effect = write
        args = {'action': 'post', 'channel': 'C0123456789', 'text': 'hello'}
        with patch.object(self.plugin, 'SlackService', return_value=fake), patch.dict(
                sys.modules, {'tools.approval_prompt': gate}):
            first = json.loads(handler(dict(args, explicit_user_request='Post hello now.')))
            second = json.loads(handler(args))
        self.assertTrue(first['success'])
        self.assertFalse(second['success'])
        self.assertEqual(second['code'], 'consent_declined')
        prompt.assert_called_once()

    def test_schema_limits_authorization_to_direct_user_send_instruction(self):
        self.handler()
        schema = self.tool['schema']
        self.assertIn('explicit_user_request', schema['parameters']['properties'])
        quote = schema['parameters']['properties']['explicit_user_request']
        self.assertEqual(quote['type'], 'string')
        for phrase in ('direct user', 'target', 'body', 'Slack', 'tool', 'page', 'ambiguous'):
            self.assertIn(phrase, quote['description'])
        self.assertIn('per_call', schema['description'])
        self.assertIn('explicit_request', schema['description'])

    def test_opt_in_send_dm_skips_prompt_for_atomic_open_and_send(self):
        out, prompt, fake = self.invoke(action='send_dm')
        self.assertTrue(out['success'], out)
        prompt.assert_not_called()
        fake.write.assert_called_once()
        self.assertEqual(fake.write.call_args.kwargs['action'], 'send_dm')

    def test_missing_or_invalid_quote_still_prompts(self):
        for action in ('post', 'send_dm'):
            for quote in (None, '', '  \t\n', 1, True, [], {}):
                with self.subTest(action=action, quote=quote):
                    out, prompt, fake = self.invoke(action=action, quote=quote)
                    self.assertTrue(out['success'], out)
                    prompt.assert_called_once()
            out, prompt, _ = self.invoke(action=action, include_quote=False)
            self.assertTrue(out['success'], out)
            prompt.assert_called_once()

    def test_default_and_per_call_policy_always_prompt(self):
        for policy in (MISSING, 'per_call'):
            for action in ('post', 'send_dm'):
                with self.subTest(policy=policy, action=action):
                    out, prompt, _ = self.invoke(policy=policy, action=action)
                    self.assertTrue(out['success'], out)
                    prompt.assert_called_once()

    def test_other_actions_cannot_use_quote_to_bypass(self):
        for action in ('update', 'delete', 'open_dm'):
            with self.subTest(action=action):
                out, prompt, _ = self.invoke(action=action)
                self.assertTrue(out['success'], out)
                prompt.assert_called_once()

    def test_unknown_policy_fails_before_service(self):
        for policy in (None, 'always', '', False, 1, [], {}):
            with self.subTest(policy=policy):
                out, prompt, fake = self.invoke(policy=policy)
                self.assertFalse(out['success'], out)
                prompt.assert_not_called()
                fake.write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
