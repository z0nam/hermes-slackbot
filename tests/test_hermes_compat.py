"""Real Hermes source compatibility, isolated home, fake executable, no Slack API."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('HERMES_AGENT_DIR'), 'needs a Hermes checkout')
class HermesCompatibility(unittest.TestCase):
    def test_plugin_discovery_and_slack_capability_note(self):
        source = Path(os.environ['HERMES_AGENT_DIR'])
        python = os.environ.get('HERMES_PYTHON', str(source / 'venv/bin/python'))
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            home = Path(directory)
            shutil.copytree(ROOT / 'plugins/slack-tools', home / 'plugins/slack-tools')
            fake = home / 'fake-sapi'
            fake.write_text('#!' + python + '\nimport json\nprint(json.dumps({"ok": True, "messages": {"matches": [], "total": 0, "paging": {"page": 1, "pages": 0}}}))\n')
            fake.chmod(0o700)
            config = {'plugins': {'enabled': ['slack-tools'], 'entries': {'slack-tools': {'settings': {
                'executable': str(fake), 'workspace_hosts': ['example.slack.com']}}}}, 'platform_toolsets': {'slack': ['slack']}}
            (home / 'config.yaml').write_text(json.dumps(config))
            env = {'PATH': os.environ['PATH'], 'HOME': str(home), 'HERMES_HOME': str(home),
                   'PYTHONPATH': str(source), 'SLACK_BOT_TOKEN': 'offline-placeholder-not-a-token',
                   'HERMES_ENABLE_PROJECT_PLUGINS': 'false', 'TMPDIR': str(home)}
            code = '''
import json, os
from hermes_cli.plugins import discover_plugins
from tools.registry import registry
from gateway.session import _slack_tools_loaded, _SLACK_TOOLS_NOTE
from tools.approval_prompt import request_elicitation_consent
assert callable(request_elicitation_consent)
discover_plugins()
entries = [registry.get_entry(n) for n in ('sapi_slack_read', 'sapi_slack_write')]
assert all(e and e.toolset == 'slack' and e.check_fn() for e in entries), entries
out = json.loads(entries[0].handler({'operation': 'search', 'query': 'offline'}))
assert out['success'] and out['data']['total'] == 0, out
assert _slack_tools_loaded() is True
os.environ['HERMES_SESSION_PLATFORM'] = 'slack'
# Real Hermes consent, no bridge: fail closed before fake sapi can execute a write.
assert request_elicitation_consent('offline probe', 'No human bridge present') == 'decline'
blocked = json.loads(entries[1].handler({'action': 'post', 'channel': 'C0123456789', 'text': 'offline'}))
assert blocked['success'] is False, blocked
os.environ.pop('SLACK_BOT_TOKEN')
assert _slack_tools_loaded() is False
print(json.dumps({'registered': [e.name for e in entries], 'enabled_note': True, 'no_token_note': False,
                  'consent_api': 'request_elicitation_consent', 'note': _SLACK_TOOLS_NOTE}))
'''
            result = subprocess.run([python, '-c', code], cwd=home, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            proof = json.loads(result.stdout.splitlines()[-1])
            self.assertEqual(proof['registered'], ['sapi_slack_read', 'sapi_slack_write'])
            print('COMPATIBILITY_PROOF ' + json.dumps(proof))
