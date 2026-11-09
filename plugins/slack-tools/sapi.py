#!/usr/bin/env python3
"""Portable `sapi`: call the Slack Web API with the owner's USER token. Stdlib only (Windows too).

    python sapi.py METHOD key=value ...                        # e.g. search.messages query=hi count=5
    python sapi.py file.download file=F0123456789 dir=PATH     # save an attachment, print its path
    python sapi.py file.upload channel=C0123456789 path=FILE [thread_ts=…] [initial_comment=…] [title=…]

Prints exactly one Slack-style JSON object on stdout ({"ok": true|false, ...}); exit code 0 on ok.
The token is SLACK_USER_TOKEN from the environment, else from the active Hermes `.env`
(HERMES_HOME, else %LOCALAPPDATA%\\hermes on Windows, else ~/.hermes). The token is never printed.
This is the same argv/JSON contract as the maintainer's `slack api` wrapper, so slack-tools can use
either one.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://slack.com/api/"
TIMEOUT = 60
MAX_UPLOAD = 1024 * 1024 * 1024  # Slack's per-file cap is 1 GB


def hermes_env() -> Path:
    home = os.environ.get("HERMES_HOME")
    if home:
        return Path(home) / ".env"
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes" / ".env"
    return Path.home() / ".hermes" / ".env"


def user_token() -> str:
    tok = os.environ.get("SLACK_USER_TOKEN", "").strip()
    if not tok:
        env = hermes_env()
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                key, _, val = line.partition("=")
                if key.strip() == "SLACK_USER_TOKEN":
                    tok = val.strip().strip('"').strip("'")
    if not tok.startswith("xoxp-"):
        raise LookupError("no_user_token")
    return tok


def request(url: str, token: str, data: bytes | None = None, ctype: str | None = None):
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    req.add_header("Authorization", "Bearer " + token)
    if ctype:
        req.add_header("Content-Type", ctype)
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def api(method: str, token: str, params: dict) -> dict:
    if not re.fullmatch(r"[a-z]+(\.[A-Za-z]+)+", method):
        return {"ok": False, "error": "invalid_method"}
    body = urllib.parse.urlencode(params).encode()
    try:
        with request(API + method, token, body, "application/x-www-form-urlencoded") as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return {"ok": False, "error": "ratelimited"}
        return {"ok": False, "error": f"http_{e.code}"}


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(str(name)).name).strip(" .")
    return name or "file"


def download(token: str, params: dict) -> dict:
    fid, folder = params.get("file", ""), params.get("dir", "")
    if not re.fullmatch(r"F[A-Z0-9]{8,}", fid) or not folder:
        return {"ok": False, "error": "invalid_arguments"}
    info = api("files.info", token, {"file": fid})
    if not info.get("ok"):
        return info
    f = info.get("file") or {}
    if f.get("filetype") == "quip":  # canvases are documents, not downloadable files
        return {"ok": False, "error": "canvas_not_downloadable"}
    url =f.get("url_private_download") or f.get("url_private") or ""
    if urllib.parse.urlsplit(url).hostname != "files.slack.com":
        return {"ok": False, "error": "no_download_url"}
    out_dir = Path(folder)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = safe_name(f.get("name") or fid)
    with request(url, token) as r:
        if "text/html" in (r.headers.get("Content-Type") or ""):
            return {"ok": False, "error": "login_page_instead_of_file"}
        data = r.read()
    if isinstance(f.get("size"), int) and len(data) != f["size"]:
        return {"ok": False, "error": "size_mismatch"}
    # Exclusive create: concurrent downloads of the same name each get their own file.
    for n in range(1000):
        target = out_dir / (name if n == 0 else f"{Path(name).stem} ({n}){Path(name).suffix}")
        try:
            with open(target, "xb") as out:
                out.write(data)
            break
        except FileExistsError:
            continue
    else:
        return {"ok": False, "error": "too_many_same_names"}
    return {"ok": True, "file": {"id": fid, "name": f.get("name"), "mimetype": f.get("mimetype"),
                                 "size": len(data), "path": str(target)}}


def upload(token: str, params: dict) -> dict:
    channel, path = params.get("channel", ""), Path(params.get("path", ""))
    if not re.fullmatch(r"[CGD][A-Z0-9]{8,}", channel) or not path.is_file():
        return {"ok": False, "error": "invalid_arguments"}
    data = path.read_bytes()
    if not data or len(data) > MAX_UPLOAD:
        return {"ok": False, "error": "invalid_file_size"}
    got = api("files.getUploadURLExternal", token, {"filename": path.name, "length": len(data)})
    if not got.get("ok"):
        return got
    up = got.get("upload_url", "")
    if urllib.parse.urlsplit(up).scheme != "https":
        return {"ok": False, "error": "bad_upload_url"}
    with request(up, token, data, "application/octet-stream") as r:
        if r.status != 200:
            return {"ok": False, "error": f"http_{r.status}"}
    done = {"files": json.dumps([{"id": got["file_id"], "title": params.get("title") or path.name}]),
            "channel_id": channel}
    for key in ("thread_ts", "initial_comment"):
        if params.get(key):
            done[key] = params[key]
    res = api("files.completeUploadExternal", token, done)
    if res.get("ok"):
        res["file_id"], res["channel"] = got["file_id"], channel
    return res


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__, file=sys.stderr)
        return 2
    method, params = argv[0], {}
    for arg in argv[1:]:
        key, sep, val = arg.partition("=")
        if not sep or not key:
            print(json.dumps({"ok": False, "error": "invalid_arguments"}))
            return 1
        params[key] = val
    try:
        token = user_token()
        handler = {"file.download": download, "file.upload": upload}.get(method)
        res = handler(token, params) if handler else api(method, token, params)
    except LookupError:
        res = {"ok": False, "error": "no_user_token"}
    except (OSError, ValueError):
        res = {"ok": False, "error": "request_failed"}
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
