# 관리자 대리 설치 절차

워크스페이스 관리자가 구성원 대신 `Hermes-<아이디>` 슬랙 앱을 만들어 주는 절차입니다. 구성원이 [셀프 설치](ko.md)를 하기엔 슬랙 앱 설정 단계가 너무 어렵다는 판단에서 나왔습니다.

- **관리자**: 앱 생성·설치·토큰 발급을 미리 끝내 둡니다. 1인당 약 3분이며 원격으로 됩니다.
- **구성원 PC**: PowerShell 한 줄을 실행하고 토큰 2개를 붙여 넣습니다. 약 5분입니다.
- **앱 소유자는 관리자**입니다. Hermes가 업데이트되면 관리자가 전원의 앱을 한 번에 갱신합니다.

토큰은 슬랙 메시지나 메일로 주고받지 않습니다. 관리자가 구성원을 그 앱의 공동 관리자(Collaborator)로 추가해 두면, 구성원이 자기 브라우저에서 슬랙에 로그인한 채로 직접 복사합니다.

## 0. 한 번만: 앱 설정 토큰 등록 (관리자, 1분)

관리자 PC에 Hermes와 이 키트가 있어야 합니다. 매니페스트를 관리자 PC의 Hermes에서 뽑기 때문입니다.

1. <https://api.slack.com/apps> 맨 아래 *Your App Configuration Tokens* → *Generate Token* → 워크스페이스를 고릅니다.
2. 두 값 중 **Refresh Token**(`xoxe-…`)을 복사합니다.
3. 토큰을 저장합니다.

   ```sh
   python3 scripts/provision_app.py token set
   ```

   맥은 키체인에 저장되고, 다른 OS는 `~/.config/hermes-slackbot/` 아래 권한 600 파일에 저장됩니다.

슬랙의 앱 설정 토큰은 12시간이면 만료되고, 만료 기간을 바꿀 수 없습니다. 대신 이 도구는 실행할 때마다 Refresh Token으로 새 토큰을 받고 새 Refresh Token을 저장합니다. 그래서 지금 한 번 등록해 두면 몇 주 뒤에 써도 됩니다.
- 실제 작업 며칠 전에 `token check`로 살아 있는지 확인하세요.
- 슬랙이 `invalid_refresh_token`이라고 답하면 1번부터 다시 하면 됩니다.

## 1. 방문 전: 구성원에게 미리 부탁할 것

방문 시간의 대부분은 Hermes 설치와 모델 로그인에서 나옵니다. 이건 구성원 본인의 계정이 필요한 일이라 미리 해 두도록 공지합니다.

- [ ] Hermes 설치를 끝내고, PowerShell에서 `hermes`를 띄워 한 마디 답이 오는지 확인
- [ ] 쓰고 싶은 아이디를 알려 주기: 영문 소문자·숫자 1-21자, 짧을수록 편함(이니셜 추천)
- [ ] 방문 당일 PC 브라우저에서 슬랙(워크스페이스)에 로그인된 상태 유지

## 2. 방문 전: 앱 만들기 (관리자, 1인당 약 3분)

```sh
python3 scripts/provision_app.py create <아이디> --user <구성원 멤버 ID U…>
```

출력에 링크가 순서대로 나옵니다.

1. **Install to Workspace**: 관리자가 직접 설치하므로 앱 승인 요청이 생기지 않습니다.
2. **App-Level Token**: *Generate Token and Scopes* → 이름 `socket` → scope `connections:write` → *Generate*
3. **Collaborators**: 구성원을 추가합니다. 구성원이 토큰을 직접 복사하는 데 필요합니다.

마지막 줄에 **구성원 PC에서 실행할 PowerShell 한 줄**이 나옵니다. 이 줄과 출력의 "Owner copies…" 링크 2개를 방문 메모에 붙여 둡니다.

`python3 scripts/provision_app.py list`로 지금까지 만든 앱을 볼 수 있습니다. 기록은 `~/.config/hermes-slackbot/apps.json`에 남고, 저장소에는 들어가지 않습니다.

## 3. 방문: 구성원 PC (약 5분)

1. PowerShell을 열고 2번에서 받은 한 줄을 붙여 넣습니다.
   - 키트를 내려받은 뒤(git이 없어도 됨) `setup_pc.py`가 실행됩니다.
   - `python`이 없다고 나오거나 Microsoft Store가 열리면, 줄 끝의 `python`을 `py`로 바꿔 다시 실행합니다.
2. 구성원 브라우저에서 "Owner copies…" 링크 2개를 엽니다. 토큰을 하나씩 복사해 물어보는 칸에 붙여 넣습니다.
   - 입력값은 화면에 보이지 않는 게 정상입니다. 붙여 넣기는 Ctrl+V나 마우스 오른쪽 클릭입니다.
3. 스크립트가 나머지를 자동으로 진행합니다.
   - 슬랙에 토큰을 확인합니다. 봇 토큰이 `Hermes-<아이디>` 것이 아니면 경고합니다.
   - `.env`에 `SLACK_BOT_TOKEN`·`SLACK_APP_TOKEN`·`SLACK_ALLOWED_USERS`(구성원 본인만)를 씁니다.
   - 플러그인을 설치하고, 게이트웨이를 등록·재시작한 뒤, 로그에서 연결을 확인합니다.
4. `Done.`이 나오면 슬랙에서 봇에게 DM "안녕"을 보내고 `/hermes-<아이디> help`를 쳐 봅니다.

이미 슬랙 토큰이 있는 PC라면 덮어쓸지 먼저 묻습니다. 예전에 직접 만든 앱이 있는 경우 해당합니다.

## 4. 방문 후 (관리자, 선택)

- 구성원을 Collaborator에서 빼도 봇은 그대로 동작합니다. 빼 두면 구성원이 앱 설정(명령·권한)을 바꿀 수 없습니다.
- 구성원이 예전에 직접 만든 Hermes 앱이 있으면 정리를 안내합니다. 앱이 둘이면 명령이 겹칩니다.

## 5. Hermes 업데이트 뒤: 전원 앱 갱신 (관리자)

```sh
python3 scripts/provision_app.py update-all --dry-run   # 무엇이 바뀌는지만 보기
python3 scripts/provision_app.py update-all
```

- 권한(스코프)이 바뀐 앱은 재설치 링크가 출력됩니다. 관리자가 눌러 재설치합니다.
- 구성원 PC에서는 할 일이 없습니다. 토큰은 그대로 유지됩니다.

## 막혔을 때

| 증상 | 원인 | 할 일 |
|---|---|---|
| `tooling.tokens.rotate failed: invalid_refresh_token` | 설정 토큰이 무효가 됨 | 0번을 다시 |
| `apps.manifest.create failed: invalid_manifest` | 관리자 PC의 Hermes 매니페스트 문제 | 출력된 `pointer`를 보고 `hermes update` 후 재시도 |
| `bot token rejected: invalid_auth` | 다른 앱 토큰이거나 앱을 재설치해 토큰이 바뀜 | OAuth 페이지에서 다시 복사 |
| `app-level token rejected` | 앱 수준 토큰의 scope가 `connections:write`가 아님 | 2번의 App-Level Token 다시 생성 |
| `MISSING slash handler` | 플러그인이 안 올라옴 | `hermes plugins list`, `.env`의 `HERMES_SLACK_SLASH` 확인 |
| `MISSING slack connected` | 게이트웨이가 슬랙에 못 붙음 | `hermes gateway status`, `gateway.log` 끝부분 확인 |
