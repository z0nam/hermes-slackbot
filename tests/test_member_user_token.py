"""Member bots with the owner's user token: portable sapi, files, DM history, upload consent."""
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_slack_tools as base  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAPI = ROOT / 'plugins/slack-tools/sapi.py'


def load_sapi():
    spec = importlib.util.spec_from_file_location('portable_sapi', SAPI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ServiceFiles(unittest.TestCase):
    # Reuse the offline fake-sapi fixture without re-running the base tests.
    setUp = base.SlackTools.setUp
    client = base.SlackTools.client
    calls = base.SlackTools.calls
    plugin_tools = base.SlackTools.plugin_tools

    def test_list_executable_runs_interpreter_and_script(self):
        self.responses.write_text(json.dumps([{'ok': True, 'messages': [], 'has_more': False}]))
        svc = base.service().SlackService([sys.executable, str(self.fake)], ['example.slack.com'])
        self.assertEqual(svc.history('C0123456789')['messages'], [])
        self.assertEqual(self.calls()[0][0], 'conversations.history')
        for bad in ([], [''], [1], {'a': 1}):
            with self.assertRaises(ValueError):
                base.service().SlackService(bad)

    def test_dm_history_finds_existing_dm_without_creating_one(self):
        c = self.client([{'ok': True, 'channel': {'id': 'D0123456789', 'user': 'U0123456789', 'is_im': True}},
                         {'ok': True, 'messages': [{'ts': '1', 'text': 'hi'}], 'has_more': False}])
        out = c.dm_history('U0123456789')
        self.assertEqual(out['channel'], 'D0123456789')
        self.assertEqual(out['messages'][0]['text'], 'hi')
        opened = self.calls()[0]
        self.assertEqual(opened[0], 'conversations.open')
        self.assertIn('prevent_creation=true', opened)

    def test_download_needs_configured_dir_and_rejects_paths_elsewhere(self):
        with self.assertRaises(ValueError):
            self.client([]).download_file('F0123456789')
        d = str(self.dir / 'dl')
        self.responses.write_text(json.dumps([{'ok': True, 'file': {'id': 'F0123456789', 'name': 'a.pdf', 'size': 3,
                                                                     'path': os.path.join(d, 'a.pdf')}}]))
        svc = base.service().SlackService(str(self.fake), [], download_dir=d)
        self.assertEqual(svc.download_file('F0123456789')['path'], os.path.join(d, 'a.pdf'))
        self.assertIn(f'dir={d}', self.calls()[0])
        self.responses.write_text(json.dumps([{'ok': True, 'file': {'id': 'F0123456789', 'path': '/etc/passwd'}}]))
        with self.assertRaises(RuntimeError):
            svc.download_file('F0123456789')

    def _file(self, data=b'abc'):
        f = self.dir / 'report.pdf'
        f.write_bytes(data)
        return str(f)

    def test_upload_asks_with_name_size_target_then_verifies(self):
        path = self._file()
        c = self.client([{'ok': True, 'file_id': 'F0123456789', 'channel': 'C0123456789'},
                         {'ok': True, 'file': {'id': 'F0123456789', 'name': 'report.pdf', 'size': 3}}])
        previews = []
        out = c.write('upload_file', channel='C0123456789', path=path, text='see',
                      approve=lambda p: previews.append(json.loads(p)) or True)
        self.assertTrue(out['verified'])
        self.assertEqual((previews[0]['file'], previews[0]['bytes'], previews[0]['channel']), ('report.pdf', 3, 'C0123456789'))
        self.assertEqual([c[0] for c in self.calls()], ['file.upload', 'files.info'])
        self.assertIn('initial_comment=see', self.calls()[0])

    def test_upload_declined_or_invalid_never_runs_sapi(self):
        path = self._file()
        c = self.client([])
        with self.assertRaises(PermissionError):
            c.write('upload_file', channel='C0123456789', path=path, approve=lambda p: False)
        for kw in ({'path': 'relative.pdf'}, {'path': str(self.dir / 'missing')}, {'path': path, 'channel': 'X1'},
                   {'path': path, 'user': 'U0123456789'}):
            args = dict({'channel': 'C0123456789'}, **kw)
            with self.assertRaises(ValueError):
                c.write('upload_file', approve=lambda p: True, **args)
        with self.assertRaises(ValueError):
            c.write('post', channel='C0123456789', text='x', path=path, approve=lambda p: True)
        self.assertFalse(self.log.exists())

    def test_upload_size_mismatch_is_unverified(self):
        c = self.client([{'ok': True, 'file_id': 'F0123456789', 'channel': 'C0123456789'},
                         {'ok': True, 'file': {'id': 'F0123456789', 'size': 99}}])
        with self.assertRaises(RuntimeError):
            c.write('upload_file', channel='C0123456789', path=self._file(), approve=lambda p: True)

    def test_explicit_request_policy_never_skips_upload_prompt(self):
        from types import ModuleType
        tools = self.plugin_tools()
        gate = ModuleType('tools.approval_prompt')
        prompts = []
        gate.request_elicitation_consent = lambda message, description, **kw: prompts.append(message) or 'decline'
        with mock.patch.dict(sys.modules, {'tools.approval_prompt': gate}):
            out = json.loads(tools['sapi_slack_write']['handler'](
                {'action': 'upload_file', 'channel': 'C0123456789', 'path': self._file(),
                 'explicit_user_request': 'upload it now'}))
        self.assertFalse(out['success'])
        self.assertEqual(len(prompts), 1)
        self.assertFalse(self.log.exists())

    def test_ready_with_list_executable_needs_script_file(self):
        tools = self.plugin_tools()  # registers with the str fake; rebuild ready via a list config
        plugin = sys.modules['slack_test_plugin']
        got = {}

        class Ctx:
            def __init__(s, exe):
                s.exe = exe
            def get_config(s, key, default=None):
                return {'executable': s.exe}.get(key, default)
            def register_tool(s, **kw):
                got[kw['name']] = kw
        plugin.register(Ctx([sys.executable, str(self.fake)]))
        self.assertTrue(got['sapi_slack_read']['check_fn']())
        plugin.register(Ctx([sys.executable, str(self.dir / 'missing.py')]))
        self.assertFalse(got['sapi_slack_read']['check_fn']())
        self.assertIn('download_file', tools['sapi_slack_read']['schema']['parameters']['properties']['operation']['enum'])


class PortableSapi(unittest.TestCase):
    def setUp(self):
        self.sapi = load_sapi()
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_token_from_hermes_env_and_never_bot_token(self):
        (self.dir / '.env').write_text('SLACK_BOT_TOKEN=xoxb-1\nSLACK_USER_TOKEN="xoxp-abc"\n')
        with mock.patch.dict(os.environ, {'HERMES_HOME': str(self.dir)}, clear=False):
            os.environ.pop('SLACK_USER_TOKEN', None)
            self.assertEqual(self.sapi.user_token(), 'xoxp-abc')
            (self.dir / '.env').write_text('SLACK_USER_TOKEN=xoxb-wrong\n')
            with self.assertRaises(LookupError):
                self.sapi.user_token()

    def test_missing_token_prints_json_error_without_network(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {'HERMES_HOME': str(self.dir)}), mock.patch('sys.stdout', out), \
                mock.patch.object(self.sapi, 'request', side_effect=AssertionError('no network')):
            os.environ.pop('SLACK_USER_TOKEN', None)
            self.assertEqual(self.sapi.main(['auth.test']), 1)
        self.assertEqual(json.loads(out.getvalue()), {'ok': False, 'error': 'no_user_token'})

    def test_safe_name_strips_paths_and_reserved_characters(self):
        self.assertEqual(self.sapi.safe_name('../../x/보고서:1.pdf'), '보고서_1.pdf')
        self.assertEqual(self.sapi.safe_name('..'), 'file')

    def test_download_writes_into_dir_and_checks_host_and_size(self):
        info = {'ok': True, 'file': {'id': 'F0123456789', 'name': 'a.txt', 'size': 3, 'mimetype': 'text/plain',
                                     'url_private_download': 'https://files.slack.com/x/a.txt'}}

        class Resp(io.BytesIO):
            headers = {'Content-Type': 'text/plain'}
            def __enter__(s):
                return s
            def __exit__(s, *a):
                return False
        with mock.patch.object(self.sapi, 'api', return_value=info), \
                mock.patch.object(self.sapi, 'request', side_effect=lambda *a, **k: Resp(b'abc')):
            out = self.sapi.download('xoxp-t', {'file': 'F0123456789', 'dir': str(self.dir)})
            again = self.sapi.download('xoxp-t', {'file': 'F0123456789', 'dir': str(self.dir)})
        self.assertTrue(out['ok'], out)
        self.assertEqual(Path(out['file']['path']).read_bytes(), b'abc')
        self.assertEqual(Path(again['file']['path']).name, 'a (1).txt')
        bad = json.loads(json.dumps(info))
        bad['file']['url_private_download'] = 'https://evil.example/a.txt'
        with mock.patch.object(self.sapi, 'api', return_value=bad):
            self.assertEqual(self.sapi.download('xoxp-t', {'file': 'F0123456789', 'dir': str(self.dir)})['error'],
                             'no_download_url')
        with mock.patch.object(self.sapi, 'api', return_value=info), \
                mock.patch.object(self.sapi, 'request', return_value=Resp(b'abcd')):
            self.assertEqual(self.sapi.download('xoxp-t', {'file': 'F0123456789', 'dir': str(self.dir)})['error'],
                             'size_mismatch')

    def test_concurrent_same_name_downloads_never_overwrite(self):
        import threading
        info = {'ok': True, 'file': {'id': 'F0123456789', 'name': 'a.txt', 'size': 1,
                                     'url_private_download': 'https://files.slack.com/x/a.txt'}}
        gate = threading.Barrier(4)

        class Resp(io.BytesIO):
            headers = {'Content-Type': 'text/plain'}
            def __enter__(s):
                gate.wait()  # all four have passed any existence check before writing
                return s
            def __exit__(s, *a):
                return False
        outs = []
        with mock.patch.object(self.sapi, 'api', return_value=info), \
                mock.patch.object(self.sapi, 'request', side_effect=lambda *a, **k: Resp(b'z')):
            threads = [threading.Thread(target=lambda: outs.append(
                self.sapi.download('xoxp-t', {'file': 'F0123456789', 'dir': str(self.dir)}))) for _ in range(4)]
            [t.start() for t in threads]
            [t.join() for t in threads]
        paths = {o['file']['path'] for o in outs}
        self.assertEqual(len(paths), 4)
        self.assertEqual(len(list(self.dir.iterdir())), 4)

    def test_upload_uses_external_upload_flow(self):
        f = self.dir / 'r.pdf'
        f.write_bytes(b'xyz')
        calls = []

        def api(method, token, params):
            calls.append((method, params))
            if method == 'files.getUploadURLExternal':
                return {'ok': True, 'upload_url': 'https://files.slack.com/upload/v1/abc', 'file_id': 'F0123456789'}
            return {'ok': True, 'files': [{'id': 'F0123456789'}]}

        class Resp:
            status = 200
            def __enter__(s):
                return s
            def __exit__(s, *a):
                return False
        with mock.patch.object(self.sapi, 'api', side_effect=api), \
                mock.patch.object(self.sapi, 'request', return_value=Resp()) as req:
            out = self.sapi.upload('xoxp-t', {'channel': 'C0123456789', 'path': str(f), 'thread_ts': '1.2'})
        self.assertTrue(out['ok'])
        self.assertEqual((out['file_id'], out['channel']), ('F0123456789', 'C0123456789'))
        self.assertEqual(calls[0], ('files.getUploadURLExternal', {'filename': 'r.pdf', 'length': 3}))
        self.assertEqual(req.call_args.args[2], b'xyz')
        self.assertEqual(calls[1][1]['channel_id'], 'C0123456789')
        self.assertEqual(calls[1][1]['thread_ts'], '1.2')


if __name__ == '__main__':
    unittest.main()
