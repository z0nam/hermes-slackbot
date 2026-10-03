"""Agent-neutral constrained Slack service backed by a user-token sapi executable."""
import json
import re
import subprocess
from urllib.parse import parse_qs, urlsplit


class SlackService:
    def __init__(self, executable='sapi', hosts=(), timeout=30):
        bounded(timeout, 1, 120, 'timeout')
        if not isinstance(hosts, (list, tuple)):
            raise ValueError('workspace_hosts must be a list of exact Slack workspace hosts')
        for host in hosts:
            validate(host, r'[a-z0-9-]+\.slack\.com', 'workspace host')
        self.executable, self.hosts, self.timeout = executable, tuple(hosts), timeout

    def _call(self, method, **params):
        try:
            result = subprocess.run([self.executable, method, *[f'{k}={v}' for k, v in params.items()]],
                                    capture_output=True, text=True, timeout=self.timeout, shell=False, encoding='utf-8')
            if result.returncode:
                raise RuntimeError('sapi failed (details suppressed)')
            data = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise RuntimeError('sapi unavailable, timed out, or returned invalid JSON; do not retry writes automatically') from None
        if not isinstance(data, dict) or data.get('ok') is not True:
            raise RuntimeError('Slack API rejected request (details suppressed)')
        if method in ('conversations.history', 'conversations.replies') and (
                not isinstance(data.get('messages'), list) or not all(isinstance(m, dict) for m in data['messages'])):
            raise RuntimeError('Slack returned malformed messages; result is unverified')
        return data

    def write(self, action, *, channel='', text='', ts='', thread_ts='', user='', approve=None):
        if action not in ('post', 'update', 'delete', 'open_dm'):
            raise ValueError('Unsupported write action')
        if action == 'open_dm':
            validate(user, r'U[A-Z0-9]{8,}', 'user ID')
            if channel or text or ts or thread_ts:
                raise ValueError('open_dm accepts only user')
        else:
            validate(channel, r'[CGD][A-Z0-9]{8,}', 'channel ID')
            if user:
                raise ValueError('Message actions do not accept user')
            if action in ('post', 'update') and (not isinstance(text, str) or not text.strip() or len(text) > 40000):
                raise ValueError('Message text must contain 1–40000 characters')
            if action in ('update', 'delete'):
                validate(ts, r'[0-9]{10}\.[0-9]{6}', 'message timestamp')
            elif ts:
                raise ValueError('post does not accept ts')
            if action == 'delete' and text:
                raise ValueError('delete does not accept text')
            if thread_ts:
                validate(thread_ts, r'[0-9]{10}\.[0-9]{6}', 'thread timestamp')
        if approve is None:
            raise PermissionError('Explicit human confirmation required for this action')
        before = None
        if action in ('update', 'delete'):
            owner = self._call('auth.test').get('user_id')
            before = self._exact(channel, ts, thread_ts)
            if not owner or not before or before.get('user') != owner or before.get('bot_id'):
                raise PermissionError('Only messages owned by the sapi user may be changed')
        preview = json.dumps({'identity': 'sapi user token (posts as a human)', 'action': action,
                              'channel': channel, 'text': text, 'ts': ts, 'thread_ts': thread_ts,
                              'user': user, 'existing_text': before.get('text', '') if before else ''}, ensure_ascii=False)
        if approve(preview) is not True:
            raise PermissionError('Explicit human confirmation required for this action')
        if action == 'open_dm':
            channel = self._call('conversations.open', users=user, return_im='true')['channel']['id']
            info = self._call('conversations.info', channel=channel)['channel']
            if info.get('id') != channel or info.get('is_im') is not True or info.get('user') != user:
                raise RuntimeError('DM open not verified; do not retry automatically')
            return {'verified': True, 'channel': channel, 'user': user}
        params = {'channel': channel, 'text': text, 'unfurl_links': 'false', 'unfurl_media': 'false'}
        if action in ('update', 'delete'):
            params['ts'] = ts
        elif thread_ts:
            params['thread_ts'] = thread_ts
        if action == 'delete':
            params = {'channel': channel, 'ts': ts}
        result = self._call({'post': 'chat.postMessage', 'update': 'chat.update', 'delete': 'chat.delete'}[action], **params)
        sent_ts = result.get('ts')
        if result.get('channel') != channel or not sent_ts or (action in ('update', 'delete') and sent_ts != ts):
            raise RuntimeError('Write outcome ambiguous; do not retry automatically')
        message = self._exact(channel, sent_ts, thread_ts)
        if (action == 'delete' and message is not None) or (action != 'delete' and (not message or message.get('text') != text)):
            raise RuntimeError('Write not verified; do not retry automatically')
        return {'verified': True, 'channel': channel, 'ts': sent_ts, 'message': message}

    def _exact(self, channel, ts, thread_ts=''):
        cursor = ''
        seen = {cursor}
        while True:
            if thread_ts:
                data = self._call('conversations.replies', channel=channel, ts=thread_ts, cursor=cursor, limit=100)
            else:
                data = self._call('conversations.history', channel=channel, oldest=ts, latest=ts, inclusive='true', limit=1)
            matches = [m for m in data.get('messages', []) if m.get('ts') == ts]
            if matches:
                return matches[0]
            following = data.get('response_metadata', {}).get('next_cursor', '')
            if not thread_ts or not following:
                if data.get('has_more'):
                    raise RuntimeError('Cannot verify truncated result')
                return None
            if following in seen:
                raise RuntimeError('Repeated pagination cursor')
            seen.add(following)
            cursor = following

    def history(self, channel, cursor='', limit=100):
        validate(channel, r'[CGD][A-Z0-9]{8,}', 'channel ID')
        bounded(limit, 1, 100, 'limit')
        data = self._call('conversations.history', channel=channel, cursor=cursor, limit=limit)
        next_cursor = data.get('response_metadata', {}).get('next_cursor', '')
        return {'messages': data.get('messages', []), 'has_more': bool(data.get('has_more') or next_cursor),
                'next_cursor': next_cursor}

    def search(self, query, count=20, page=1):
        if not isinstance(query, str) or not query.strip():
            raise ValueError('Search query is required')
        bounded(count, 1, 100, 'count')
        bounded(page, 1, 100, 'page')
        data = self._call('search.messages', query=query, count=count, page=page)['messages']
        paging = data['paging']
        more = paging['page'] < paging['pages']
        return {'matches': data['matches'], 'total': data['total'], 'page': paging['page'],
                'pages': paging['pages'], 'has_more': more, 'next_page': paging['page'] + 1 if more else None}

    def read_link(self, link, cursor='', limit=100):
        bounded(limit, 1, 100, 'limit')
        channel, ts = parse_link(link, self.hosts)
        query = parse_qs(urlsplit(link).query)
        parents = query.get('thread_ts', [ts])
        if len(parents) != 1:
            raise ValueError('Ambiguous thread timestamp')
        parent = parents[0]
        validate(parent, r'[0-9]{10}\.[0-9]{6}', 'thread timestamp')
        found = self._call('conversations.history', channel=channel, latest=parent, inclusive='true', limit=1)
        roots = [m for m in found.get('messages', []) if m.get('ts') == parent]
        if len(roots) != 1:
            raise RuntimeError('Exact linked message not found')
        root = roots[0]
        page = self._call('conversations.replies', channel=channel, ts=root.get('thread_ts', parent),
                          cursor=cursor, limit=limit)
        next_cursor = page.get('response_metadata', {}).get('next_cursor', '')
        return {'channel': channel, 'ts': ts, 'root': root,
                'replies': [m for m in page.get('messages', []) if m.get('ts') != root.get('thread_ts', parent)],
                'has_more': bool(page.get('has_more') or next_cursor), 'next_cursor': next_cursor}


def bounded(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid ' + label)


def validate(value, pattern, label):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError('Invalid ' + label)


def parse_link(link, hosts):
    url = urlsplit(link)
    match = re.fullmatch(r'/archives/([CGD][A-Z0-9]{8,})/p([0-9]{10})([0-9]{6})', url.path)
    if (url.scheme != 'https' or url.netloc not in hosts or not match
            or not re.fullmatch(r'[a-z0-9-]+\.slack\.com', url.netloc)):
        raise ValueError('Invalid or unapproved Slack message link')
    return match[1], match[2] + '.' + match[3]


def main():
    import argparse
    import sys
    parser = argparse.ArgumentParser(description='Constrained Slack reads/writes through a user-token sapi. Writes need a real interactive human confirmation.')
    parser.add_argument('--sapi', default='sapi', help='Executable path or PATH name (no shell)')
    parser.add_argument('--workspace-host', action='append', default=[], help='Allowed exact workspace host for read_link')
    parser.add_argument('operation', choices=['read_link', 'search', 'history', 'post', 'update', 'delete', 'open_dm'])
    parser.add_argument('--args', default='{}', help='JSON object of operation arguments; timestamps must be strings')
    options = parser.parse_args()

    def consent(preview):
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            return False
        print(preview, file=sys.stderr)
        print('Type yes to approve this one Slack action: ', end='', file=sys.stderr, flush=True)
        return sys.stdin.readline().strip() == 'yes'

    try:
        args = json.loads(options.args)
        if not isinstance(args, dict):
            raise ValueError('Arguments must be an object')
        client = SlackService(options.sapi, options.workspace_host)
        if options.operation in ('read_link', 'search', 'history'):
            data = getattr(client, options.operation)(**args)
        else:
            data = client.write(options.operation, **args, approve=consent)
        print(json.dumps({'success': True, 'data': data}, ensure_ascii=False))
        return 0
    except Exception:
        print(json.dumps({'success': False, 'error': 'Slack request denied or failed; details suppressed. Never automatically retry writes.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
