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

## 6. 아이디 바꾸기 (관리자 + 구성원 PC)

같은 앱의 이름과 명령만 바꿉니다. 앱을 새로 만들지 않으므로 토큰도 그대로 씁니다.

```sh
python3 scripts/provision_app.py rename <옛 아이디> <새 아이디> --dry-run   # 바뀔 항목만 보기
python3 scripts/provision_app.py rename <옛 아이디> <새 아이디>
```

- 슬랙 쪽에서는 앱 이름·봇 이름·설명 속 아이디·슬래시 명령 네 가지만 바뀝니다. 권한(스코프)은 그대로라 재설치가 필요 없고, 설치된 토큰도 계속 유효합니다.
- 레지스트리(`apps.json`)의 키도 새 아이디로 옮겨지고, `renamed_from`에 옛 아이디가 남습니다.
- **구성원 PC에서 할 일**: `HERMES_SLACK_SLASH`를 새 명령으로 바꾸고 게이트웨이를 재시작합니다. JAIX 키트를 쓰는 PC는 `jaix hermes rename <새 아이디>`, 그 밖에는 키트 폴더에서 `python scripts/install.py <새 아이디>`를 실행한 뒤 `hermes gateway restart`를 실행합니다.
  - 이 작업 전까지는 `/hermes-<새 아이디>`를 치면 "앱이 반응하지 않아 실패했습니다"가 뜹니다. DM은 계속 됩니다.
- 슬랙이 봇의 내부 사용자 이름(`auth.test`의 `user`)은 옛 이름 그대로 둘 수 있습니다. 나중에 같은 PC에서 `setup_pc.py`를 새 아이디로 다시 돌리면 "봇 이름이 다르다"는 경고가 나올 수 있는데, 앱 ID가 같으면 그대로 진행해도 됩니다.

## 7. 키트 권한이 늘었을 때: 기존 앱 갱신 (2026-11, `groups:write`·`chat:write.customize`)

키트 매니페스트에 봇 권한 두 개가 추가됐습니다. 그 전에 만든 앱은 아래 순서로 맞춥니다. **순서가 중요합니다.** 재설치(3단계)를 마치기 전에 구성원 PC에 새 플러그인을 깔면, `slack-model-display`가 권한 없이 보낸 사람 이름을 바꾸려 하게 됩니다.

- `groups:write`: 봇이 주인 전용 비공개 채널 `hermes-<아이디>`를 만들고 주인을 초대합니다(`conversations.create`, `conversations.invite`).
- `chat:write.customize`: 답변의 보낸 사람 이름을 `Hermes-<아이디> (모델명)`으로 바꿉니다(`slack-model-display`).

1. studio의 키트를 최신으로 맞춥니다: `git -C ~/dev/hermes-slackbot pull`
2. 바뀔 항목을 확인합니다. 앱마다 `/oauth_config/scopes/bot (+chat:write.customize +groups:write)`만 나와야 합니다. 다른 항목이 나오면 멈추고 확인합니다.

   ```sh
   python3 scripts/provision_app.py update-all --dry-run
   ```

   - 열 수 없는 앱(지운 앱, 관리자가 협업자에서 빠진 앱)은 `export failed: no_permission`으로 표시되고, 나머지는 계속 확인합니다.
3. 적용한 뒤 재설치합니다.

   ```sh
   python3 scripts/provision_app.py update-all
   ```

   - 매니페스트만 바뀐 상태에서는 기존 토큰이 예전 권한 그대로 계속 동작합니다. 새 권한은 재설치해야 붙습니다.
   - 앱마다 `→ scopes changed: reinstall at https://api.slack.com/apps/<A…>/install-on-team`가 출력됩니다. 관리자가 하나씩 열어 **허용**을 누릅니다. 앱 승인제가 켜져 있으면 관리자 승인도 거칩니다.
4. 토큰이 그대로인지 확인합니다. 같은 워크스페이스에 재설치하면 새 권한이 기존 설치에 더해지고, 봇 토큰(`xoxb-`)과 앱 수준 토큰(`xapp-`)은 보통 그대로입니다. 그래서 **원칙적으로 토큰 재복사는 필요 없습니다.**
   - 첫 앱을 재설치한 직후, 그 구성원 봇에 DM을 보내 답이 오는지 봅니다. 답이 오면 나머지도 같습니다.
   - 답이 없고 구성원 PC 게이트웨이 로그에 `invalid_auth`·`token_revoked`가 보이면 토큰이 바뀐 것입니다. 이때만 `jaix hermes handoff <아이디> --user <U…>`(또는 Collaborator 복사)로 토큰을 다시 놓습니다.
5. 구성원 PC를 갱신합니다. JAIX 키트를 쓰는 PC는 jaix 업데이트로 반영됩니다. 그 밖에는 키트 폴더에서 `python scripts/install.py <아이디>`를 실행한 뒤 `hermes gateway restart`를 합니다. `slack-forwarded`·`slack-model-display`가 설치되고 `base_name`이 `Hermes-<아이디>`로 맞춰집니다.
   - 아직 재설치하지 않은 앱이면 `--no-model-display`를 붙입니다.

## jaix-setup 경로: 연결 코드 하나로 (관리자가 토큰을 놓는다)

제주연구원 PC에 `jaix-setup.exe`로 설치할 때 쓰는 경로입니다. 설계 원문은 [jaix-kit `docs/design-hermes-unattended.md`](https://github.com/jeju-inst/jaix-kit/blob/main/docs/design-hermes-unattended.md) §3.1에 있고, 2026-10-30 사용자가 승인했습니다. 위 3번(방문)과 **Collaborator 추가 단계가 없습니다.** 구성원은 토큰을 직접 복사하지 않습니다.

1. 2번까지는 같습니다. 앱을 만들고 설치한 뒤 App-Level Token을 발급합니다. Collaborator는 추가하지 않습니다.
2. 관리자가 studio에서 다음을 실행합니다. 봇 토큰과 앱 수준 토큰을 숨김 입력으로 붙여 넣으면 슬랙에 확인한 뒤 1회용 **연결 코드**(`JX-…`)를 출력합니다.

   ```sh
   jaix hermes handoff <아이디> --user <구성원 멤버 ID U…>
   ```

   - 묶음은 studio의 jaix 배포처(`jaix.namun.net`)에만 최대 72시간 머뭅니다. 원내 IP에서 한 번 받아 가면 바로 지워집니다.
   - 토큰은 슬랙 메시지나 메일로 보내지 않습니다. **연결 코드는 슬랙 DM으로 보내도 됩니다.** 코드는 토큰이 아니고, 원내망에서 한 번만 쓸 수 있으며, 남이 먼저 쓰면 구성원 설치가 "이미 사용됨"으로 실패해서 드러납니다.
3. 구성원은 `jaix-setup.exe`에서 "슬랙으로도 쓰기"를 고르고 연결 코드를 붙여 넣습니다. jaix가 Hermes 설치, `setup_pc.py --secrets-file`(무인), 게이트웨이 등록까지 합니다.

### 여러 명을 한 번에: `onboard_batch.py`

앱을 여러 개 만든 뒤에는 2번(설치·App-Level Token)과 `handoff`를 사람마다 터미널 한 화면에서 이어 갑니다. 1인당 1-2분 걸립니다.

```sh
# studio: jaix 는 PATH 에 두지 않고 jaix-kit main 체크아웃에서 돌린다(재발급 확인 --again 이 든 판이 필요)
git -C ~/dev/jaix-kit pull -q
python3 scripts/onboard_batch.py --roster ~/명단.tsv --jaix "uv run -q --project ~/dev/jaix-kit jaix"
```

- **명단**은 머리줄이 있는 TSV·CSV입니다. 첫 열은 이름이고, `U…` 모양의 칸을 멤버 ID로 읽습니다. 개인정보이므로 저장소 밖에 둡니다. 레지스트리(`apps.json`)에서 그 멤버가 주인인 앱만 진행하고, 앱이 없는 사람은 이름만 알려 줍니다.
- **사람마다 하는 일**
  1. Install 페이지가 열리면 [허용]을 누르고 Enter를 칩니다.
  2. Basic Information과 OAuth & Permissions가 열리면 App-Level Token(`connections:write`)을 만들고 Enter를 칩니다.
  3. `jaix hermes handoff`의 숨김 입력에 xoxb와 xapp를 차례로 붙여 넣습니다. 도구는 터미널을 jaix에 그대로 넘기므로 토큰을 보지 않습니다. jaix 출력(stdout)에서 JX 코드만 골라냅니다.
- 사람 사이에서는 Enter=시작, `s`=건너뛰기, `q`=중단입니다. 진행 기록은 `~/.config/hermes-slackbot/onboard-progress.json`에 남습니다. 같은 명령을 다시 실행하면 끝난 사람은 빼고, 건너뛴 사람부터 다시 묻습니다. 끝난 사람을 다시 하려면 `--only <아이디>`를 씁니다.
- 이미 코드를 낸 사람은 jaix가 종료 코드 3으로 멈춥니다. 이때 도구가 `--again`으로 다시 낼지 묻고, 묻지 않고 다시 내는 일은 없습니다.
- **DM용 코드 모음**은 `~/.config/hermes-slackbot/jx-codes-<날짜>.txt`(0600)에 "이름 · 코드"로 한 줄씩 쌓입니다. 다 보낸 뒤에는 지웁니다.

**유출이 의심되거나 퇴사·PC 교체 때**: 앱 설정에서 *OAuth & Permissions → Revoke Tokens*, *Basic Information → App-Level Tokens → Revoke*를 누르고 재설치한 뒤 `handoff`를 다시 합니다. 급하면 앱을 지웁니다.

`setup_pc.py`의 무인 옵션:
- `--secrets-file f.json`: `bot_token`·`app_token`을 담은 파일입니다. 읽는 즉시 지웁니다. 토큰을 명령줄에 싣지 않습니다.
- `--replace`: 이미 있는 슬랙 토큰을 묻지 않고 바꿉니다. 이 옵션 없이 무인으로 돌리면 멈춥니다.
- `--yes`: 봇 이름이 `Hermes-<아이디>`가 아니어도 계속합니다.
- 무인에서는 `.env`를 바꾸기 전에 `.env.bak-<시각>`으로 백업합니다. `hermes gateway install`이 실패하면 오류로 끝납니다. 이때 게이트웨이는 입력을 받지 않으므로 Windows에서 UAC 없이 시작프로그램 폴더로 등록됩니다.

## 막혔을 때

| 증상 | 원인 | 할 일 |
|---|---|---|
| `tooling.tokens.rotate failed: invalid_refresh_token` | 설정 토큰이 무효가 됨 | 0번을 다시 |
| `apps.manifest.create failed: invalid_manifest` | 관리자 PC의 Hermes 매니페스트 문제 | 출력된 `pointer`를 보고 `hermes update` 후 재시도 |
| `bot token rejected: invalid_auth` | 다른 앱 토큰이거나 앱을 재설치해 토큰이 바뀜 | OAuth 페이지에서 다시 복사 |
| `app-level token rejected` | 앱 수준 토큰의 scope가 `connections:write`가 아님 | 2번의 App-Level Token 다시 생성 |
| `MISSING slash handler` | 플러그인이 안 올라옴 | `hermes plugins list`, `.env`의 `HERMES_SLACK_SLASH` 확인 |
| `MISSING slack connected` | 게이트웨이가 슬랙에 못 붙음 | `hermes gateway status`, `gateway.log` 끝부분 확인 |
