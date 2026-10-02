# Hermes에게 맡기는 설치 프롬프트

이 키트의 설치를 사람이 직접 하지 않고, **본인 PC의 Hermes에게 시키는** 프롬프트입니다. 아래 코드 블록 안쪽을 통째로 복사해서 붙여 넣으면, Hermes가 아이디를 묻는 것부터 시작해 한 단계씩 진행합니다.

- **붙여 넣는 곳:** PC 터미널(Windows는 PowerShell)에서 띄운 `hermes`, 또는 Hermes 데스크톱 앱
- **붙여 넣으면 안 되는 곳:** 슬랙의 Hermes 봇 DM. 중간에 봇을 재시작하기 때문에 대화가 끊깁니다.
- **사람이 직접 하는 것:** 슬랙 앱 설정 화면에서 복사·붙여넣기, 토큰 복사, 재설치 버튼 누르기

새로 설치하는 경우와, 기본 방식(`/hermes` 등 명령 수십 개)으로 이미 만든 앱을 고치는 경우 모두 이 프롬프트 하나로 됩니다. Hermes가 1단계에서 "슬랙 앱이 이미 있느냐"를 물어보고 그 답으로 갈래를 나눕니다.

```text
내 PC의 Hermes를 슬랙 개인 봇으로 연결(또는 기존 연결을 정리)해 줘. 이전 대화에 다른 안내가 있었다면 무시하고 아래 순서만 따른다.

환경: 운영체제를 먼저 확인하고 그에 맞는 셸 명령을 써라(Windows면 PowerShell). 경로는 하드코딩하지 말고 `hermes config env-path`(=.env 위치)의 폴더를 HERMES_HOME 으로 쓴다(Windows 기본값은 %LOCALAPPDATA%\hermes). 파이썬은 `python`, 안 되면 `py`(Windows) 또는 `python3`.

목표: 슬랙 앱 이름 = Hermes-<ID>, 슬래시 명령 = /hermes-<ID> 딱 하나(하위명령으로 사용: /hermes-<ID> new, /hermes-<ID> help …). 같은 워크스페이스에 다른 사람의 개인 Hermes 앱도 있을 수 있어서, /hermes·/help·/new 같은 공용 이름은 쓰지 않는다. 기존 앱에 명령이 여러 개 있으면 하나씩 지우거나 추가하지 말고, 키트가 만든 매니페스트로 통째로 교체한다(그러면 슬랙의 명령 개수 제한과도 상관없다).

지켜야 할 것: 토큰 값(xoxb-, xapp-)은 절대 화면에 출력하지 말 것. 파일을 바꾸거나 지우기 전에 무엇을 할지 보여 주고 내 확인을 받을 것. 슬랙 앱의 권한·이벤트는 키트가 만든 매니페스트대로 두고 임의로 고치지 말 것.

0. 아이디 정하기: 가장 먼저 나에게 봇에 쓸 아이디(<ID>)를 물어봐라. 규칙: 영문 소문자·숫자·`-`·`_` 만, 첫 글자는 영문 소문자나 숫자, 1-21자. 명령을 매번 쳐야 하니 짧을수록 편하다는 점(예: 이니셜 2-3글자)도 알려 줘라. 내가 답하면 규칙에 맞는지 확인하고, 앱 이름 Hermes-<ID>·명령 /hermes-<ID> 로 확정해도 되는지 한 번 확인받아라. 이후 모든 단계의 <ID> 는 이 값으로 바꿔서 실행한다.

1. 현재 상태 점검(바꾸지 말고 보고만):
   - `hermes --version`, `hermes gateway status`, `hermes plugins list`
   - .env 에서 SLACK_BOT_TOKEN·SLACK_APP_TOKEN 은 있음/없음만, SLACK_ALLOWED_USERS·SLACK_HOME_CHANNEL·HERMES_SLACK_SLASH 는 값까지 보여 줘라(비밀값 아님).
   - `git --version`, 파이썬 버전 확인.
   - 그다음 나에게 직접 물어봐라: "이 워크스페이스에 내 Hermes 슬랙 앱이 이미 있나요? (https://api.slack.com/apps 의 Your Apps 목록에서 확인)". 갈래는 이 답으로 정한다 — 있으면 [기존 앱 정리], 없으면 [새로 만들기]. 토큰이 있는지 없는지만 보고 판단하지 마라(앱은 만들었는데 아직 토큰을 안 넣었거나, 앱은 지웠는데 옛 토큰이 남아 있는 경우가 흔하다). 내 답과 토큰 상태가 엇갈리면 그 사실을 알려 줘라: 앱이 있는데 토큰이 없으면 5번 끝에 토큰 입력 단계를 추가하고, 앱이 없는데 토큰이 남아 있으면 새 앱을 만든 뒤 `hermes gateway setup` 으로 새 토큰으로 덮어쓰게 한다.

2. 키트 받기: 홈 폴더 아래 hermes-slackbot 에 https://github.com/z0nam/hermes-slackbot 을 clone 한다. 이미 있으면 `git pull`. 그 폴더에서 `python -m unittest discover -s tests` 를 돌려 통과하는지 확인한다(1개 skip 은 정상).

3. 플러그인 설치: 예전에 손으로 만든 `<HERMES_HOME>/plugins/slack-namespace` 가 있고 키트가 설치한 것이 아니라면 `<HERMES_HOME>/plugins-backup-<오늘날짜>` 로 옮겨 백업한다(삭제 말고 이동, 내 확인 후). 그다음 키트 폴더에서 `python scripts/install.py <ID>` 를 실행한다(복사 방식, --link 쓰지 말 것. Windows 경로 구분자는 알아서 맞춰라). 끝나면 `hermes plugins list` 에서 slack-namespace·fallback-alert 가 enabled 인지, .env 에 HERMES_SLACK_SLASH=hermes-<ID> 가 있는지 확인한다.

4. 매니페스트 만들기: 키트 폴더에서 `python scripts/make_manifest.py <ID> --out <바탕화면>/hermes-slack-manifest.json` 실행(바탕화면 경로는 OS에 맞게). 만든 파일에서 앱 이름(display_information.name), 봇 이름(features.bot_user.display_name), 슬래시 명령 목록만 요약해 보여 줘라. 이름 2개가 Hermes-<ID> 이고 명령이 /hermes-<ID> 하나여야 정상이다.

5. 내가 직접 할 일을 단계별로 안내하고, 내가 "완료"라고 하기 전에는 다음 단계로 넘어가지 마라.
   [새로 만들기]
   - https://api.slack.com/apps → Create New App → From a manifest → 워크스페이스 선택 → 바탕화면 hermes-slack-manifest.json 내용 전체 붙여넣기 → Create → Install to Workspace(관리자 승인이 필요하면 관리자에게 요청)
   - Basic Information → App-Level Tokens → Generate(scope: connections:write) → xapp- 토큰을 복사해 둔다
   - OAuth & Permissions → Bot User OAuth Token(xoxb-)을 복사해 둔다
   - 슬랙에서 내 프로필 → ⋮ → 멤버 ID 복사(U로 시작)
   - 그다음 터미널에서 내가 직접 `hermes gateway setup` 을 실행해 Slack 을 고르고 xoxb·xapp·멤버 ID 를 입력하게 안내해라(토큰을 너에게 붙여 넣게 하지 마라). 허용 사용자는 내 멤버 ID 하나만.
   [기존 앱 정리]
   - https://api.slack.com/apps → 내 기존 Hermes 앱 → Features → App Manifest → Edit
   - 기존 내용을 전부 지우고 hermes-slack-manifest.json 내용 전체 붙여넣기 → Save(명령 수십 개가 1개로 바뀌는 게 정상)
   - "Agent view 로 바꾸면 되돌릴 수 없다"는 확인이 뜨면 진행, 재설치 안내가 뜨면 Install App → Reinstall to Workspace
   - Basic Information → Display Information 의 App name 이 Hermes-<ID> 로 바뀌었는지 확인, 안 바뀌었으면 직접 수정
   - SLACK_ALLOWED_USERS 가 내 멤버 ID 하나가 아니면 고치는 방법을 안내해라. 이 봇은 내 PC의 파일·셸 권한으로 움직이는 개인 에이전트라 나만 써야 한다.
   - (1번에서 토큰이 없었던 경우) Basic Information → App-Level Tokens 에서 xapp- 토큰(scope: connections:write, 없으면 새로 생성), OAuth & Permissions 에서 xoxb- 토큰을 복사한 뒤, 터미널에서 내가 직접 `hermes gateway setup` 을 실행해 입력하게 안내해라(토큰을 너에게 붙여 넣게 하지 마라).

6. 서비스 등록·재시작: 게이트웨이가 서비스로 등록돼 있지 않으면 `hermes gateway install`, 그다음 `hermes gateway restart`. 이후 `<HERMES_HOME>/logs/gateway.log` 끝부분에서 다음 세 줄을 확인해라(토큰이 들어간 줄은 출력하지 말 것):
   - `slack-namespace: /hermes-<ID> -> /hermes handler registered`
   - `Wired native handlers from plugin 'slack-namespace'`
   - `slack connected`

7. 테스트 안내: 슬랙에서 (1) 봇(Hermes-<ID>)에게 DM 으로 "안녕"을 보내 응답이 오는지, (2) 나와의 DM 같은 아무 채널에서 `/hermes-<ID> help` 를 쳐서 도움말이 오는지 확인하게 해라. 결과에 따라:
   - "유효한 명령어가 아닙니다" → 5번(매니페스트 Save·재설치)이 반영 안 됨. 5번을 다시 안내.
   - "앱이 반응하지 않아 실패했습니다" → 플러그인이 안 올라온 것. 3번·6번 결과를 다시 점검.
   - DM 에 응답이 없음 → `hermes gateway status`, SLACK_ALLOWED_USERS, gateway.log 의 오류 줄을 확인.
```

## 막혔을 때

| 증상 | 원인 | 할 일 |
|---|---|---|
| `/hermes-<ID>` 가 "유효한 명령어가 아닙니다" | 슬랙 앱에 명령이 등록되지 않음 | App Manifest 교체 → Save → 재설치 |
| "앱이 반응하지 않아 실패했습니다" | 슬랙은 명령을 보냈는데 Hermes가 받지 못함 | `hermes plugins list`, `.env` 의 `HERMES_SLACK_SLASH`, 게이트웨이 재시작 |
| "Too many commands already (25)" | 기존 앱에 명령을 하나 더 추가하려 함 | 추가하지 말고 매니페스트를 통째로 교체 |
| 봇 이름이 여전히 `Hermes` | 매니페스트만으로 앱 이름이 안 바뀌는 경우 | Basic Information → Display Information 에서 직접 수정 |
