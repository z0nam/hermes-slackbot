"""Offline channel metadata slices, using the real subprocess service."""
import json
import sys
import unittest

import test_slack_tools

CHANNEL = 'C0123456789'
OWNER = 'U0123456789'


def info(value='old', field='purpose', **overrides):
    return dict(id=CHANNEL, name='example-channel', is_member=True, is_im=False,
                is_mpim=False, **{field: {'value': value}}, **overrides)


class ChannelMetadata(unittest.TestCase):
    def setUp(self):
        self.fixture = test_slack_tools.SlackTools(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_set_purpose_previews_identity_old_new_and_reads_exact_channel_back(self):
        client = self.fixture.client([
            {'ok': True, 'user_id': OWNER}, {'ok': True, 'channel': info()},
            {'ok': True, 'purpose': 'new purpose'},
            {'ok': True, 'channel': info('new purpose')}])
        previews = []
        result = client.write('set_purpose', channel=CHANNEL, purpose='new purpose',
                              approve=lambda p: previews.append(json.loads(p)) or True)
        self.assertEqual(result, {'verified': True, 'channel': CHANNEL, 'purpose': 'new purpose'})
        self.assertEqual(previews[0]['author'], OWNER)
        self.assertEqual(previews[0]['channel'], CHANNEL)
        self.assertEqual(previews[0]['channel_name'], 'example-channel')
        self.assertEqual(previews[0]['existing_purpose'], 'old')
        self.assertEqual(previews[0]['purpose'], 'new purpose')
        self.assertIn('human', previews[0]['identity'])
        self.assertEqual(self.fixture.calls(), [
            ['auth.test'], ['conversations.info', 'channel=' + CHANNEL],
            ['conversations.setPurpose', 'channel=' + CHANNEL, 'purpose=new purpose'],
            ['conversations.info', 'channel=' + CHANNEL]])

    def test_set_topic_and_explicit_empty_clear_are_verified(self):
        for channel in (CHANNEL, 'G0123456789'):
            for value in ('new topic', ''):
                with self.subTest(channel=channel, value=value):
                    before = dict(info(field='topic'), id=channel)
                    after = dict(info(value, field='topic'), id=channel)
                    client = self.fixture.client([
                        {'ok': True, 'user_id': OWNER}, {'ok': True, 'channel': before},
                        {'ok': True, 'channel': after}, {'ok': True, 'channel': after}])
                    previews = []
                    result = client.write('set_topic', channel=channel, topic=value,
                                          approve=lambda p: previews.append(json.loads(p)) or True)
                    self.assertEqual(result, {'verified': True, 'channel': channel, 'topic': value})
                    self.assertEqual(previews[0]['existing_topic'], 'old')
                    self.assertEqual(previews[0]['topic'], value)
                    self.assertEqual(self.fixture.calls()[-2],
                                     ['conversations.setTopic', 'channel=' + channel, 'topic=' + value])

    def test_metadata_arguments_are_exclusive_bounded_strings_before_io(self):
        client = self.fixture.client([])
        for field in ('purpose', 'topic'):
            base = {'action': 'set_' + field, 'channel': CHANNEL, field: 'new'}
            cases = [{k: v for k, v in base.items() if k != field}]
            cases += [dict(base, **{field: value}) for value in (None, False, 1, [], {}, '한' * 251, 'a\x00b')]
            cases += [dict(base, channel=c) for c in ('C1', 'D0123456789', None)]
            cases += [dict(base, **{key: value}) for key, value in (
                ('text', 'unexpected'), ('ts', '1760000000.000001'), ('thread_ts', '1760000000.000001'),
                ('user', OWNER), ('path', '/file'), ('topic' if field == 'purpose' else 'purpose', ''))]
            for args in cases:
                with self.subTest(args=args), self.assertRaises(ValueError):
                    client.write(**args, approve=lambda p: self.fail('validation precedes consent'))
        for action, args in [('post', {'text': 'x'}), ('upload_file', {'path': '/file'})]:
            for field in ('purpose', 'topic'):
                with self.subTest(action=action, field=field), self.assertRaises(ValueError):
                    client.write(action, channel=CHANNEL, **args, **{field: ''}, approve=lambda p: True)
        self.assertFalse(self.fixture.log.exists())

    def test_metadata_length_boundary_and_purpose_clear_remain_exact(self):
        for field in ('purpose', 'topic'):
            for value in ('', '한' * 250, ' spaced \n value '):
                with self.subTest(field=field, value=value):
                    after = info(value, field=field)
                    response = {'ok': True, 'channel': after} if field == 'topic' else {'ok': True}
                    client = self.fixture.client([
                        {'ok': True, 'user_id': OWNER}, {'ok': True, 'channel': info(field=field)},
                        response, {'ok': True, 'channel': after}])
                    self.assertEqual(client.write('set_' + field, channel=CHANNEL, **{field: value},
                                                  approve=lambda p: True)[field], value)
                    self.assertIn(field + '=' + value, self.fixture.calls()[-2])

    def test_metadata_preflight_rejects_unverified_channel_membership_or_author(self):
        for field in ('purpose', 'topic'):
            good = info(field=field)
            broken = [None, {}, dict(good, id='C9876543210'), dict(good, is_member=False),
                      {k: v for k, v in good.items() if k != 'is_member'}, dict(good, is_im=True),
                      dict(good, is_mpim=True), dict(good, **{field: None}), dict(good, **{field: {}}),
                      dict(good, **{field: {'value': 3}}), {k: v for k, v in good.items() if k != field}]
            for channel_info in broken:
                with self.subTest(field=field, info=channel_info):
                    self.fixture.log.unlink(missing_ok=True)
                    client = self.fixture.client([{'ok': True, 'user_id': OWNER}, {'ok': True, 'channel': channel_info}])
                    with self.assertRaises((RuntimeError, PermissionError)):
                        client.write('set_' + field, channel=CHANNEL, **{field: 'new'},
                                     approve=lambda p: self.fail('invalid preflight must not prompt'))
                    self.assertEqual([c[0] for c in self.fixture.calls()], ['auth.test', 'conversations.info'])
            for auth in ({'ok': True}, {'ok': True, 'user_id': 'U1'},
                         {'ok': True, 'user_id': OWNER, 'bot_id': 'B0123456789'}):
                with self.subTest(auth=auth):
                    self.fixture.log.unlink(missing_ok=True)
                    client = self.fixture.client([auth])
                    with self.assertRaises((ValueError, PermissionError)):
                        client.write('set_' + field, channel=CHANNEL, **{field: 'new'}, approve=lambda p: True)
                    self.assertEqual(self.fixture.calls(), [['auth.test']])

    def test_metadata_absent_declined_or_non_boolean_consent_never_mutates(self):
        for field in ('purpose', 'topic'):
            client = self.fixture.client([])
            with self.assertRaises(PermissionError):
                client.write('set_' + field, channel=CHANNEL, **{field: ''})
            self.assertFalse(self.fixture.log.exists())
            for answer in (False, None, 'yes', 1):
                client = self.fixture.client([{'ok': True, 'user_id': OWNER}, {'ok': True, 'channel': info(field=field)}])
                with self.assertRaises(PermissionError):
                    client.write('set_' + field, channel=CHANNEL, **{field: ''}, approve=lambda p: answer)
                self.assertFalse(any(c[0].startswith('conversations.set') for c in self.fixture.calls()))
            self.fixture.log.unlink()

    def test_metadata_write_and_readback_must_identify_exact_field_and_channel(self):
        for field in ('purpose', 'topic'):
            good = info('new', field=field)
            for after in (None, {}, dict(good, id='C9876543210'), dict(good, **{field: None}),
                          dict(good, **{field: {}}), dict(good, **{field: {'value': 'different'}})):
                with self.subTest(field=field, after=after):
                    self.fixture.log.unlink(missing_ok=True)
                    response = {'ok': True, 'channel': good} if field == 'topic' else {'ok': True}
                    client = self.fixture.client([
                        {'ok': True, 'user_id': OWNER}, {'ok': True, 'channel': info(field=field)},
                        response, {'ok': True, 'channel': after}])
                    with self.assertRaises(RuntimeError):
                        client.write('set_' + field, channel=CHANNEL, **{field: 'new'}, approve=lambda p: True)
                    self.assertEqual(len(self.fixture.calls()), 4)
            bad_responses = [{'ok': True, 'channel': None}, {'ok': True, 'channel': {}},
                             {'ok': True, 'channel': dict(good, id='C9876543210')},
                             {'ok': True, 'channel': dict(good, **{field: {'value': 'other'}})},
                             {'ok': True, field: 'wrong'}]
            if field == 'topic':
                bad_responses += [{'ok': True}, {'ok': True, 'channel': {'id': CHANNEL}}]
            for response in bad_responses:
                with self.subTest(field=field, response=response):
                    self.fixture.log.unlink(missing_ok=True)
                    client = self.fixture.client([
                        {'ok': True, 'user_id': OWNER}, {'ok': True, 'channel': info(field=field)},
                        response, {'ok': True, 'channel': good}])
                    with self.assertRaises(RuntimeError):
                        client.write('set_' + field, channel=CHANNEL, **{field: 'new'}, approve=lambda p: True)
                    self.assertEqual(len(self.fixture.calls()), 3, 'ambiguous mutation is never retried')

    def test_registered_metadata_schema_and_explicit_policy_still_require_human(self):
        import sys
        from types import ModuleType
        from unittest.mock import Mock, patch
        from test_slack_approval_policy import ApprovalPolicy
        policy = ApprovalPolicy(methodName='runTest')
        self.addCleanup(policy.doCleanups)
        handler = policy.handler('explicit_request')
        properties = policy.tool['schema']['parameters']['properties']
        for field in ('purpose', 'topic'):
            self.assertIn('set_' + field, properties['action']['enum'])
            self.assertEqual(properties[field]['maxLength'], 250)
            self.assertEqual(properties[field]['type'], 'string')
            for answer, code in [('decline', 'consent_declined'), ('cancel', 'consent_expired'),
                                 (RuntimeError('private bridge failure'), 'consent_unavailable'), ('accept', None)]:
                with self.subTest(field=field, answer=answer):
                    self.fixture.log.unlink(missing_ok=True)
                    after = info('new', field=field)
                    response = {'ok': True, 'channel': after} if field == 'topic' else {'ok': True}
                    client = self.fixture.client([
                        {'ok': True, 'user_id': OWNER}, {'ok': True, 'channel': info(field=field)},
                        response, {'ok': True, 'channel': after}])
                    gate = ModuleType('tools.approval_prompt')
                    prompt = Mock(side_effect=answer) if isinstance(answer, Exception) else Mock(return_value=answer)
                    setattr(gate, 'request_elicitation_consent', prompt)
                    with patch.object(policy.plugin, 'SlackService', return_value=client), patch.dict(
                            sys.modules, {'tools.approval_prompt': gate}):
                        result = json.loads(handler({'action': 'set_' + field, 'channel': CHANNEL,
                                                     field: 'new', 'explicit_user_request': 'Change it now.'}))
                    prompt.assert_called_once()
                    self.assertEqual(result['success'], code is None)
                    if code:
                        self.assertEqual(result['code'], code)
                        self.assertEqual(len(self.fixture.calls()), 2)
                        self.assertNotIn('private', json.dumps(result))
                    else:
                        self.assertTrue(result['data']['verified'])

    def test_even_null_metadata_arguments_cannot_be_silently_ignored(self):
        client = self.fixture.client([])
        for field in ('purpose', 'topic'):
            other = 'topic' if field == 'purpose' else 'purpose'
            for args in ({'action': 'set_' + field, field: 'new', other: None},
                         {'action': 'post', 'text': 'hello', field: None}):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    client.write(channel=CHANNEL, **args, approve=lambda p: self.fail('must reject before consent'))
        self.assertFalse(self.fixture.log.exists())

    def test_metadata_scope_diagnostics_and_manifest_are_narrow_and_user_only(self):
        import importlib.util
        path = test_slack_tools.ROOT / 'scripts/make_manifest.py'
        spec = importlib.util.spec_from_file_location('metadata_manifest', path)
        assert spec and spec.loader
        manifest = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(manifest)
        for scope in ('channels:write.topic', 'groups:write.topic'):
            self.assertIn(scope, manifest.oauth_app_manifest()['oauth_config']['scopes']['user'])
            self.assertNotIn(scope, manifest.kit_manifest({}, 'alice')['oauth_config']['scopes']['bot'])
        self.assertNotIn('bot', manifest.oauth_app_manifest()['oauth_config']['scopes'])
        self.assertNotIn('channels:write', manifest.KIT_USER_SCOPES)
        self.assertNotIn('groups:write', manifest.KIT_USER_SCOPES)
        for field, scope in [('purpose', 'channels:write.topic'), ('topic', 'groups:write.topic')]:
            method = 'conversations.set' + field.title()
            error = {'ok': False, 'error': 'missing_scope', 'needed': scope, 'provided': 'private data'}
            for stage in ('preflight', 'write', 'verification'):
                with self.subTest(field=field, stage=stage):
                    self.fixture.log.unlink(missing_ok=True)
                    prefix = [{'ok': True, 'user_id': OWNER}]
                    expected_method = 'conversations.info' if stage != 'write' else method
                    if stage != 'preflight':
                        prefix.append({'ok': True, 'channel': info(field=field)})
                    if stage == 'verification':
                        prefix.append({'ok': True, 'channel': info('new', field=field)} if field == 'topic' else {'ok': True})
                    client = self.fixture.client(prefix + [error])
                    with self.assertRaises(RuntimeError) as caught:
                        client.write('set_' + field, channel=CHANNEL, **{field: 'new'}, approve=lambda p: True)
                    # The exception class must come from this client's loaded module.
                    out = client._call.__globals__['failure'](caught.exception)
                    self.assertEqual((out['code'], out['method'], out['stage'], out['needed']),
                                     ('missing_scope', expected_method, stage, [scope]))
                    self.assertNotIn('private', json.dumps(out))
                    self.assertEqual(len(self.fixture.calls()), len(prefix) + 1)

    def test_cli_metadata_actions_cannot_be_approved_by_piped_yes(self):
        import subprocess
        import sys
        for field in ('purpose', 'topic'):
            self.fixture.log.unlink(missing_ok=True)
            self.fixture.client([{'ok': True, 'user_id': OWNER}, {'ok': True, 'channel': info(field=field)}])
            result = subprocess.run([sys.executable, str(test_slack_tools.SERVICE), '--sapi', str(self.fixture.fake),
                                     'set_' + field, '--args', json.dumps({'channel': CHANNEL, field: ''})],
                                    input='yes\n', capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(json.loads(result.stdout)['success'])
            self.assertEqual([c[0] for c in self.fixture.calls()], ['auth.test', 'conversations.info'])

    def test_metadata_slack_restrictions_are_structured_and_never_retried(self):
        for field in ('purpose', 'topic'):
            for code in ('is_archived', 'user_is_restricted', 'too_long', 'invalid_arguments',
                         'method_not_supported_for_channel_type', 'not_in_channel'):
                with self.subTest(field=field, code=code):
                    self.fixture.log.unlink(missing_ok=True)
                    client = self.fixture.client([
                        {'ok': True, 'user_id': OWNER}, {'ok': True, 'channel': info(field=field)},
                        {'ok': False, 'error': code, 'details': 'private data'}])
                    with self.assertRaises(RuntimeError) as caught:
                        client.write('set_' + field, channel=CHANNEL, **{field: 'new'}, approve=lambda p: True)
                    out = client._call.__globals__['failure'](caught.exception)
                    self.assertEqual((out['code'], out['method'], out['stage']),
                                     (code, 'conversations.set' + field.title(), 'write'))
                    self.assertNotIn('private', json.dumps(out))
                    self.assertEqual(len(self.fixture.calls()), 3)

    @unittest.skipIf(sys.version_info < (3, 10), 'Bundled sapi already requires Python 3.10+')
    def test_bundled_transport_supports_metadata_methods_and_empty_values(self):
        # Regression coverage for the unchanged generic stdlib transport: no method allowlist.
        import importlib.util
        import io
        from unittest.mock import patch
        from urllib.parse import parse_qs
        path = test_slack_tools.ROOT / 'plugins/slack-tools/sapi.py'
        spec = importlib.util.spec_from_file_location('metadata_transport', path)
        assert spec and spec.loader
        transport = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(transport)
        for field in ('purpose', 'topic'):
            method = 'conversations.set' + field.title()
            with patch.object(transport, 'request', return_value=io.BytesIO(b'{"ok": true}')) as request:
                self.assertEqual(transport.api(method, 'offline-placeholder', {'channel': CHANNEL, field: ''}), {'ok': True})
            self.assertEqual(request.call_args.args[0], 'https://slack.com/api/' + method)
            self.assertEqual(parse_qs(request.call_args.args[2].decode(), keep_blank_values=True),
                             {'channel': [CHANNEL], field: ['']})

    def test_metadata_rejects_malformed_unrelated_fields_instead_of_ignoring_them(self):
        client = self.fixture.client([])
        for field in ('purpose', 'topic'):
            for key, value in (('text', None), ('ts', 0), ('thread_ts', []), ('user', {}), ('path', False)):
                with self.subTest(field=field, key=key), self.assertRaises(ValueError):
                    client.write('set_' + field, channel=CHANNEL, **{field: 'new', key: value},
                                 approve=lambda p: self.fail('invalid argument must not prompt'))
        self.assertFalse(self.fixture.log.exists())


if __name__ == '__main__':
    unittest.main()
