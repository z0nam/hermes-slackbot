"""Offline canvas slices (channel canvas create/edit as the human user), using the real subprocess service."""
import importlib.util
import json
import unittest

import test_slack_tools

CHANNEL = 'C0123456789'
CANVAS = 'F0123456789'
OWNER = 'U0123456789'
SECTION = 'temp:C:AAAAAAAAAAAAAAAAAAAAAAAAAAA'


def chan(canvas=None, **over):
    props = {'canvas': {'file_id': canvas}} if canvas else {}
    return dict(id=CHANNEL, name='hermes-test', is_member=True, is_im=False, is_mpim=False, properties=props, **over)


def canvas_file(updated=100):
    return {'id': CANVAS, 'filetype': 'quip', 'title': 'Notes', 'updated': updated}


class Canvas(unittest.TestCase):
    def setUp(self):
        self.fixture = test_slack_tools.SlackTools(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_create_channel_canvas_previews_and_verifies_channel_property(self):
        client = self.fixture.client([
            {'ok': True, 'user_id': OWNER}, {'ok': True, 'channel': chan()},
            {'ok': True, 'canvas_id': CANVAS}, {'ok': True, 'channel': chan(CANVAS)}])
        previews = []
        out = client.write('create_channel_canvas', channel=CHANNEL, text='# 활용 가이드\n- 보고', title='가이드',
                           approve=lambda p: previews.append(json.loads(p)) or True)
        self.assertEqual(out, {'verified': True, 'channel': CHANNEL, 'canvas': CANVAS})
        self.assertEqual(previews[0]['author'], OWNER)
        self.assertEqual(previews[0]['channel_name'], 'hermes-test')
        self.assertEqual(previews[0]['markdown'], '# 활용 가이드\n- 보고')
        calls = self.fixture.calls()
        self.assertEqual(calls[2][0], 'conversations.canvases.create')
        self.assertIn('channel_id=' + CHANNEL, calls[2])
        self.assertIn('title=가이드', calls[2])
        doc = json.loads(next(a for a in calls[2] if a.startswith('document_content=')).split('=', 1)[1])
        self.assertEqual(doc, {'type': 'markdown', 'markdown': '# 활용 가이드\n- 보고'})

    def test_create_refuses_when_channel_already_has_canvas_before_asking(self):
        client = self.fixture.client([{'ok': True, 'user_id': OWNER}, {'ok': True, 'channel': chan(CANVAS)}])
        asked = []
        with self.assertRaises(ValueError) as e:
            client.write('create_channel_canvas', channel=CHANNEL, text='x', approve=lambda p: asked.append(p) or True)
        self.assertIn(CANVAS, str(e.exception))
        self.assertEqual(asked, [])

    def test_declined_or_missing_consent_never_writes(self):
        for approve in (None, lambda p: False):
            client = self.fixture.client([{'ok': True, 'user_id': OWNER}, {'ok': True, 'channel': chan()}])
            with self.assertRaises(PermissionError):
                client.write('create_channel_canvas', channel=CHANNEL, text='x', approve=approve)
        self.assertNotIn('conversations.canvases.create', [c[0] for c in self.fixture.calls()])

    def test_bot_token_is_refused(self):
        client = self.fixture.client([{'ok': True, 'user_id': OWNER, 'bot_id': 'B0123456789'}])
        with self.assertRaises(PermissionError):
            client.write('create_channel_canvas', channel=CHANNEL, text='x', approve=lambda p: True)

    def test_edit_append_and_section_replace(self):
        for mode, section, op in (('append', '', 'insert_at_end'), ('replace', SECTION, 'replace')):
            with self.subTest(mode=mode):
                client = self.fixture.client([
                    {'ok': True, 'user_id': OWNER}, {'ok': True, 'file': canvas_file(100)},
                    {'ok': True}, {'ok': True, 'file': canvas_file(120)}])
                previews = []
                out = client.write('edit_canvas', canvas=CANVAS, mode=mode, section_id=section, text='## 추가',
                                   approve=lambda p: previews.append(json.loads(p)) or True)
                self.assertEqual(out, {'verified': True, 'canvas': CANVAS, 'mode': mode})
                self.assertEqual(previews[0]['canvas_title'], 'Notes')
                edit = self.fixture.calls()[-2]
                self.assertEqual(edit[0], 'canvases.edit')
                change = json.loads(next(a for a in edit if a.startswith('changes=')).split('=', 1)[1])[0]
                self.assertEqual(change['operation'], op)
                self.assertEqual(change['document_content']['markdown'], '## 추가')
                self.assertEqual(change.get('section_id', ''), section)

    def test_edit_arguments_are_bounded(self):
        client = self.fixture.client([])
        bad = [dict(canvas=CANVAS, mode='delete', text='x'), dict(canvas=CANVAS, mode='append', section_id=SECTION, text='x'),
               dict(canvas='C0123456789', mode='append', text='x'), dict(canvas=CANVAS, mode='append', text=' ')]
        for kwargs in bad:
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                client.write('edit_canvas', approve=lambda p: True, **kwargs)
        with self.assertRaises(ValueError):
            client.write('post', channel=CHANNEL, text='x', canvas=CANVAS, approve=lambda p: True)
        for text in ('가' * 20001, '"\n' * 9000):  # too long, or too long once JSON-escaped: refused before any call
            with self.assertRaises(ValueError):
                client.write('create_channel_canvas', channel=CHANNEL, text=text, approve=lambda p: True)
        self.assertFalse(self.fixture.log.exists())

    def test_reads_channel_canvas_and_sections(self):
        client = self.fixture.client([{'ok': True, 'channel': chan(CANVAS)},
                                      {'ok': True, 'sections': [{'id': SECTION}]}])
        self.assertEqual(client.channel_canvas(CHANNEL), {'channel': CHANNEL, 'channel_name': 'hermes-test', 'canvas': CANVAS})
        self.assertEqual(client.canvas_sections(CANVAS, contains_text='보고'), {'canvas': CANVAS, 'sections': [SECTION]})
        crit = json.loads(next(a for a in self.fixture.calls()[1] if a.startswith('criteria=')).split('=', 1)[1])
        self.assertEqual(crit, {'contains_text': '보고'})

    def test_scopes_are_in_manifest_and_errors_pass_through(self):
        spec = importlib.util.spec_from_file_location('mm', test_slack_tools.ROOT / 'scripts/make_manifest.py')
        mm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mm)
        for scope in ('canvases:read', 'canvases:write'):
            self.assertIn(scope, mm.KIT_USER_SCOPES)
        svc = test_slack_tools.service()
        err = svc.SlackRequestError({'error': 'missing_scope', 'needed': 'canvases:write'}, 'canvases.edit', 'write')
        self.assertEqual(err.details, {'code': 'missing_scope', 'method': 'canvases.edit', 'stage': 'write',
                                       'needed': ['canvases:write']})
        self.assertEqual(svc.SlackRequestError({'error': 'channel_canvas_already_exists'}, 'conversations.canvases.create',
                                               'write').details['code'], 'channel_canvas_already_exists')


if __name__ == '__main__':
    unittest.main()
