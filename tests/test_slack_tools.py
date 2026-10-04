"""Offline vertical slices; fake sapi never touches credentials or network."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / 'plugins/slack-tools/service.py'


def service():
    spec = importlib.util.spec_from_file_location('slack_service', SERVICE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SlackTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.fake = self.dir / 'sapi'
        self.log = self.dir / 'calls.jsonl'
        self.responses = self.dir / 'responses.json'
        self.responses.write_text('[]')
        self.fake.write_text('#!' + sys.executable + '\n' + '''import json, sys
from pathlib import Path
root = Path(__file__).parent
with (root / 'calls.jsonl').open('a') as f: f.write(json.dumps(sys.argv[1:]) + '\\n')
p = root / 'responses.json'
r = json.loads(p.read_text())
print(json.dumps(r.pop(0)))
p.write_text(json.dumps(r))
''')
        self.fake.chmod(0o700)

    def client(self, responses):
        self.responses.write_text(json.dumps(responses))
        self.assertTrue(hasattr(service(), 'SlackService'), 'sapi service missing')
        return service().SlackService(str(self.fake), ['example.slack.com'])

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_read_link_returns_root_and_explicit_reply_pagination(self):
        root = {'ts': '1760000000.000001', 'text': 'root', 'reply_count': 2}
        client = self.client([
            {'ok': True, 'messages': [root]},
            {'ok': True, 'messages': [root, {'ts': '1760000001.000001', 'text': 'reply'}], 'has_more': True, 'response_metadata': {'next_cursor': 'next'}}])
        out = client.read_link('https://example.slack.com/archives/C0123456789/p1760000000000001')
        self.assertEqual(out['root'], root)
        self.assertEqual(len(out['replies']), 1)
        self.assertTrue(out['has_more'])
        self.assertEqual(out['next_cursor'], 'next')
        self.assertIn('latest=1760000000.000001', self.calls()[0])
        self.assertEqual(self.calls()[1][0], 'conversations.replies')

    def test_search_exposes_total_and_page(self):
        c = self.client([{'ok': True, 'messages': {'matches': [{'text': 'hit'}], 'total': 7, 'paging': {'page': 2, 'pages': 3}}}])
        self.assertTrue(hasattr(c, 'search'), 'search missing')
        out = c.search('budget in:#general', count=3, page=2)
        self.assertEqual(out, {'matches': [{'text': 'hit'}], 'total': 7, 'page': 2, 'pages': 3, 'has_more': True, 'next_page': 3})
        self.assertIn('query=budget in:#general', self.calls()[0])

    def test_history_exposes_cursor(self):
        c = self.client([{'ok': True, 'messages': [{'text': 'one'}], 'has_more': True, 'response_metadata': {'next_cursor': 'c2'}}])
        self.assertTrue(hasattr(c, 'history'), 'history missing')
        self.assertEqual(c.history('C0123456789', cursor='c1', limit=2), {'messages': [{'text': 'one'}], 'has_more': True, 'next_cursor': 'c2'})
        self.assertIn('cursor=c1', self.calls()[0])

    def test_write_without_human_consent_does_not_spawn_sapi(self):
        c = self.client([])
        self.assertTrue(hasattr(c, 'write'), 'confirmed writes missing')
        for approve in [None, lambda preview: False]:
            with self.assertRaises(PermissionError):
                c.write('post', channel='C0123456789', text='human message', approve=approve)
        self.assertFalse(self.log.exists())

    def test_post_and_reply_are_verified_with_unfurls_off(self):
        for parent in ['', '1760000000.000001']:
            with self.subTest(parent=parent):
                msg = {'ts': '1760000001.000001', 'text': 'Hello ; $HOME', 'user': 'U0123456789'}
                c = self.client([{'ok': True, 'channel': 'C0123456789', 'ts': msg['ts']},
                                 {'ok': True, 'messages': [msg]}])
                previews = []
                out = c.write('post', channel='C0123456789', text=msg['text'], thread_ts=parent,
                              approve=lambda p: previews.append(p) or True)
                self.assertIsInstance(out, dict, 'post result missing')
                self.assertTrue(out['verified'])
                self.assertEqual(out['message'], msg)
                self.assertIn(msg['text'], previews[0])
                self.assertIn('unfurl_links=false', self.calls()[-2])
                self.assertIn('unfurl_media=false', self.calls()[-2])
                self.assertEqual(self.calls()[-1][0], 'conversations.replies' if parent else 'conversations.history')

    def test_update_checks_owner_and_reads_back(self):
        before = {'ts': '1760000000.000001', 'user': 'U0123456789', 'text': 'old'}
        after = dict(before, text='new')
        c = self.client([{'ok': True, 'user_id': before['user']}, {'ok': True, 'messages': [before]},
                         {'ok': True, 'channel': 'C0123456789', 'ts': before['ts']}, {'ok': True, 'messages': [after]}])
        out = c.write('update', channel='C0123456789', ts=before['ts'], text='new', approve=lambda p: True)
        self.assertEqual(out['message'], after)
        self.assertEqual([x[0] for x in self.calls()], ['auth.test', 'conversations.history', 'chat.update', 'conversations.history'])

    def test_delete_verifies_absence(self):
        ts = '1760000000.000001'
        c = self.client([{'ok': True, 'user_id': 'U0123456789'},
                         {'ok': True, 'messages': [{'ts': ts, 'user': 'U0123456789', 'text': 'delete me'}]},
                         {'ok': True, 'channel': 'C0123456789', 'ts': ts}, {'ok': True, 'messages': []}])
        out = c.write('delete', channel='C0123456789', ts=ts, approve=lambda p: True)
        self.assertTrue(out['verified'])
        self.assertIsNone(out['message'])
        self.assertEqual(self.calls()[2][0], 'chat.delete')

    def test_dm_open_is_confirmed_and_verified(self):
        c = self.client([{'ok': True, 'channel': {'id': 'D0123456789'}},
                         {'ok': True, 'channel': {'id': 'D0123456789', 'is_im': True, 'user': 'U0123456789'}}])
        out = c.write('open_dm', user='U0123456789', approve=lambda p: True)
        self.assertTrue(out['verified'])
        self.assertEqual(out['channel'], 'D0123456789')
        self.assertEqual([x[0] for x in self.calls()], ['conversations.open', 'conversations.info'])

    def test_dm_open_accepts_enterprise_user_id(self):
        user = 'W0123456789'
        c = self.client([{'ok': True, 'channel': {'id': 'D0123456789'}},
                         {'ok': True, 'channel': {'id': 'D0123456789', 'is_im': True, 'user': user}}])
        previews = []
        out = c.write('open_dm', user=user, approve=lambda p: previews.append(p) or True)
        self.assertTrue(out['verified'])
        self.assertEqual(out['user'], user)
        self.assertIn(user, previews[0])
        self.assertIn('users=' + user, self.calls()[0])
        self.assertEqual([x[0] for x in self.calls()], ['conversations.open', 'conversations.info'])

    def test_invalid_write_arguments_fail_before_confirmation(self):
        c = self.client([])
        for args in [dict(action='files.delete', channel='C0123456789'), dict(action='post', channel='C1', text='x'),
                     dict(action='update', channel='C0123456789', ts='1.2', text='x'),
                     dict(action='post', channel='C0123456789', text=''), dict(action='open_dm', user='U1')]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                c.write(**args, approve=lambda p: self.fail('must validate before consent'))
        self.assertFalse(self.log.exists())

    def test_read_bounds_are_validated_before_sapi(self):
        c = self.client([])
        for op in [lambda: c.history('C1'), lambda: c.history('C0123456789', limit=0),
                   lambda: c.search('', page=1), lambda: c.search('x', page=0),
                   lambda: c.read_link('https://example.slack.com/archives/C0123456789/p1760000000000001', limit=101)]:
            with self.assertRaises(ValueError):
                op()
        self.assertFalse(self.log.exists())

    def test_malformed_transport_output_is_sanitized(self):
        c = self.client([])
        self.fake.write_text('#!' + sys.executable + '\nprint("xoxp-fake-secret")\n')
        with self.assertRaises(RuntimeError) as err:
            c.search('x')
        self.assertNotIn('xoxp', str(err.exception))

    def plugin_tools(self):
        plugin_path = ROOT / 'plugins/slack-tools/__init__.py'
        self.assertTrue(plugin_path.exists(), 'Hermes plugin missing')
        spec = importlib.util.spec_from_file_location('slack_test_plugin', plugin_path, submodule_search_locations=[str(plugin_path.parent)])
        assert spec and spec.loader
        plugin = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = plugin
        spec.loader.exec_module(plugin)
        registered = {}
        class Context:
            def get_config(_, key, default=None):
                return {'executable': str(self.fake), 'workspace_hosts': ['example.slack.com']}.get(key, default)
            def register_tool(_, **kw):
                registered[kw['name']] = kw
        plugin.register(Context())
        return registered

    def test_plugin_registers_read_handler_in_native_slack_toolset(self):
        self.responses.write_text(json.dumps([{'ok': True, 'messages': {'matches': [], 'total': 0, 'paging': {'page': 1, 'pages': 0}}}]))
        read = self.plugin_tools()['sapi_slack_read']
        self.assertEqual(read['toolset'], 'slack')
        self.assertTrue(read['check_fn']())
        out = json.loads(read['handler']({'operation': 'search', 'query': 'x'}, task_id='offline'))
        self.assertTrue(out['success'])
        self.assertEqual(out['data']['total'], 0)

    def test_plugin_write_uses_per_call_hermes_consent_not_model_flag(self):
        from types import ModuleType
        from unittest.mock import patch
        tools = self.plugin_tools()
        self.assertIn('sapi_slack_write', tools, 'write tool missing')
        gate = ModuleType('tools.approval_prompt')
        prompts = []
        gate.request_elicitation_consent = lambda message, description, **kw: prompts.append(message) or 'decline'
        with patch.dict(sys.modules, {'tools.approval_prompt': gate}):
            out = json.loads(tools['sapi_slack_write']['handler']({'action': 'post', 'channel': 'C0123456789', 'text': 'body'}))
        self.assertFalse(out['success'])
        self.assertIn('body', prompts[0])
        self.assertIn('C0123456789', prompts[0])
        self.assertFalse(self.log.exists())
        self.assertNotIn('confirmed', tools['sapi_slack_write']['schema']['parameters']['properties'])

    def test_standalone_cli_search_runs_fake_sapi(self):
        import subprocess
        self.responses.write_text(json.dumps([{'ok': True, 'messages': {'matches': [], 'total': 0, 'paging': {'page': 1, 'pages': 0}}}]))
        result = subprocess.run([sys.executable, str(SERVICE), '--sapi', str(self.fake), 'search', '--args', '{"query":"x"}'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip(), 'standalone CLI missing')
        self.assertEqual(json.loads(result.stdout)['data']['total'], 0)

    def test_installer_tools_only_preserves_existing_plugins_and_env(self):
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('offline_install', ROOT / 'scripts/install.py')
        inst = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inst)
        env = self.dir / '.env'
        env.write_text('HERMES_SLACK_SLASH=existing\n')
        old = self.dir / 'plugins/slack-namespace'
        old.mkdir(parents=True)
        (old / 'marker').write_text('keep')
        calls = []
        def fake_run(*args):
            calls.append(args)
            return str(env) if args == ('config', 'env-path') else ''
        with patch.object(inst, 'run', fake_run), patch.object(sys, 'argv', ['install.py', '--tools-only']):
            inst.main()
        self.assertTrue((self.dir / 'plugins/slack-tools/service.py').exists())
        self.assertEqual((old / 'marker').read_text(), 'keep')
        self.assertEqual(env.read_text(), 'HERMES_SLACK_SLASH=existing\n')
        self.assertIn(('plugins', 'enable', 'slack-tools'), calls)
        self.assertFalse(any('restart' in c for c in calls))

    def test_reply_permalink_uses_parent_timestamp(self):
        root = {'ts': '1760000000.000001', 'text': 'parent'}
        c = self.client([{'ok': True, 'messages': [root]}, {'ok': True, 'messages': [root, {'ts': '1760000001.000002', 'text': 'reply'}]}])
        out = c.read_link('https://example.slack.com/archives/C0123456789/p1760000001000002?thread_ts=1760000000.000001&cid=C0123456789')
        self.assertEqual(out['root'], root)
        self.assertEqual(out['ts'], '1760000001.000002')
        self.assertIn('latest=1760000000.000001', self.calls()[0])
        self.assertIn('ts=1760000000.000001', self.calls()[1])
        self.assertEqual(len(out['replies']), 1)

    def test_mutation_rejects_mismatched_returned_timestamp(self):
        ts = '1760000000.000001'
        c = self.client([{'ok': True, 'user_id': 'U0123456789'}, {'ok': True, 'messages': [{'ts': ts, 'user': 'U0123456789'}]},
                         {'ok': True, 'channel': 'C0123456789', 'ts': '1760000001.000001'}, {'ok': True, 'messages': []}])
        with self.assertRaises(RuntimeError):
            c.write('delete', channel='C0123456789', ts=ts, approve=lambda p: True)
        self.assertEqual(len(self.calls()), 3)

    def test_verification_rejects_cursor_cycles(self):
        c = self.client([{'ok': True, 'messages': [], 'response_metadata': {'next_cursor': cursor}} for cursor in ['a', 'b', 'a', '']])
        with self.assertRaises(RuntimeError):
            c._exact('C0123456789', '1760000001.000001', '1760000000.000001')
        self.assertEqual(len(self.calls()), 3)

    def test_timeout_cannot_be_disabled(self):
        for timeout in [None, 0, -1, 121, True]:
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                service().SlackService(str(self.fake), timeout=timeout)

    def test_bad_and_foreign_links_never_execute(self):
        mod = service()
        for link in ['http://example.slack.com/archives/C0123456789/p1760000000000001',
                     'https://other.slack.com/archives/C0123456789/p1760000000000001',
                     'https://example.slack.com.evil.test/archives/C0123456789/p1760000000000001',
                     'https://example.slack.com/archives/C1/p1760000000000001',
                     'https://example.slack.com/archives/C0123456789/p176000000000001',
                     'https://user@example.slack.com/archives/C0123456789/p1760000000000001']:
            with self.subTest(link=link), self.assertRaises(ValueError):
                mod.parse_link(link, ['example.slack.com'])

    def test_update_refuses_other_users(self):
        ts = '1760000000.000001'
        c = self.client([{'ok': True, 'user_id': 'U0123456789'}, {'ok': True, 'messages': [{'ts': ts, 'user': 'U9876543210'}]}])
        with self.assertRaises(PermissionError):
            c.write('update', channel='C0123456789', ts=ts, text='x', approve=lambda p: True)
        self.assertEqual([x[0] for x in self.calls()], ['auth.test', 'conversations.history'])

    def test_ambiguous_post_never_retries(self):
        c = self.client([{'ok': True, 'channel': 'C0123456789'}])
        with self.assertRaises(RuntimeError):
            c.write('post', channel='C0123456789', text='x', approve=lambda p: True)
        self.assertEqual(len(self.calls()), 1)

    def test_readback_failure_never_reports_success_or_retries(self):
        c = self.client([{'ok': True, 'channel': 'C0123456789', 'ts': '1760000000.000001'}, {'ok': True, 'messages': []}])
        with self.assertRaises(RuntimeError):
            c.write('post', channel='C0123456789', text='x', approve=lambda p: True)
        self.assertEqual(len(self.calls()), 2)

    def test_reply_readback_follows_cursor(self):
        msg = {'ts': '1760000001.000001', 'text': 'x'}
        c = self.client([{'ok': True, 'channel': 'C0123456789', 'ts': msg['ts']},
                         {'ok': True, 'messages': [], 'has_more': True, 'response_metadata': {'next_cursor': 'next'}},
                         {'ok': True, 'messages': [msg]}])
        self.assertTrue(c.write('post', channel='C0123456789', thread_ts='1760000000.000001', text='x', approve=lambda p: True)['verified'])
        self.assertIn('cursor=next', self.calls()[-1])

    def test_cli_cannot_be_confirmed_by_piped_yes(self):
        import subprocess
        result = subprocess.run([sys.executable, str(SERVICE), '--sapi', str(self.fake), 'post', '--args', '{"channel":"C0123456789","text":"x"}'], input='yes\n', capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)['success'])
        self.assertFalse(self.log.exists())

    def test_missing_executable_hides_tools(self):
        self.fake.unlink()
        self.assertFalse(self.plugin_tools()['sapi_slack_read']['check_fn']())

    def test_delete_consent_shows_existing_message_body(self):
        ts = '1760000000.000001'
        c = self.client([{'ok': True, 'user_id': 'U0123456789'}, {'ok': True, 'messages': [{'ts': ts, 'user': 'U0123456789', 'text': 'Exact body to remove'}]}])
        prompts = []
        with self.assertRaises(PermissionError):
            c.write('delete', channel='C0123456789', ts=ts, approve=lambda p: prompts.append(p) or False)
        self.assertIn('Exact body to remove', prompts[0])
        self.assertEqual([x[0] for x in self.calls()], ['auth.test', 'conversations.history'])

    def test_delete_does_not_treat_malformed_readback_as_absence(self):
        ts = '1760000000.000001'
        c = self.client([{'ok': True, 'user_id': 'U0123456789'}, {'ok': True, 'messages': [{'ts': ts, 'user': 'U0123456789'}]},
                         {'ok': True, 'channel': 'C0123456789', 'ts': ts}, {'ok': True}])
        with self.assertRaises(RuntimeError):
            c.write('delete', channel='C0123456789', ts=ts, approve=lambda p: True)

    def test_workspace_allowlist_is_not_a_substring_string(self):
        with self.assertRaises(ValueError):
            service().SlackService(str(self.fake), hosts='not-example.slack.com')

    def test_link_preserves_channel_and_microseconds(self):
        self.assertTrue(SERVICE.exists(), 'neutral Slack service missing')
        self.assertEqual(service().parse_link('https://example.slack.com/archives/C0123456789/p1760000000000001', ['example.slack.com']), ('C0123456789', '1760000000.000001'))


if __name__ == '__main__':
    unittest.main()
