# hermes-slackbot 한국어 안내

같은 슬랙 워크스페이스에서 여러 사람이 각자 자기 Hermes를 개인 봇으로 붙일 때 쓰는 키트입니다.

## 무엇이 문제인가

Hermes 기본 안내대로 슬랙 앱을 만들면 두 가지 문제가 생깁니다.

- 슬래시 명령 50여 개(`/hermes`, `/help`, `/new` …)가 워크스페이스 전체에 등록됩니다. 두 번째 사람이 설치하면 명령이 겹치고, 나중에 설치한 앱이 명령을 가져갑니다.
- 앱 이름이 모두 `Hermes`라서 누구 봇인지 구분이 안 되고, 공용 봇으로 오해받기 쉽습니다. 실제로는 주인 PC의 파일·셸·계정 권한으로 움직이는 개인 에이전트입니다.

이 키트로 설치하면 사람마다 앱 이름은 `Hermes-<아이디>`, 명령은 `/hermes-<아이디>` 하나가 됩니다.

> **직접 하기 번거로우면** [Hermes에게 설치를 맡기는 프롬프트](hermes-prompt.ko.md)를 내 PC의 Hermes에 붙여 넣으세요. 아이디를 묻는 것부터 한 단계씩 진행합니다.

```
/hermes-alice new            → 새 대화
/hermes-alice model opus     → 모델 변경
/hermes-alice 오늘 할 일은?    → 일반 질문
```

## 설치 (Windows PowerShell 기준, 맥·리눅스도 같은 명령)

> 맥과 Windows 11에서 실제로 설치해 한 워크스페이스에 개인 봇 두 개를 함께 운영하는 것까지 확인했습니다(2026-10).

준비: Hermes가 설치돼 있고(`hermes --version`), 모델 설정이 끝나 있어야 합니다.

```powershell
git clone https://github.com/z0nam/hermes-slackbot
cd hermes-slackbot

# 1. 슬랙 앱 설정 파일 만들기 (아이디는 영어 소문자, 슬랙 핸들 추천)
python scripts\make_manifest.py alice --out slack-manifest.json
```

2. **슬랙 앱 만들기**: <https://api.slack.com/apps> → *Create New App* → *From a manifest* → 워크스페이스 선택 → `slack-manifest.json` 내용 붙여넣기 → *Create* → *Install to Workspace*
   - *Basic Information* → *App-Level Tokens* → `connections:write` 권한으로 토큰 생성 → **`xapp-…`** 복사
   - *OAuth & Permissions* → **`xoxb-…`** 복사
   - 내 **멤버 ID**: 슬랙에서 내 프로필 → ⋮ → *멤버 ID 복사* (`U…`)
   - 워크스페이스에서 앱 설치에 관리자 승인이 필요하면 관리자에게 요청합니다.

```powershell
# 3. 토큰 입력 + 나만 허용 (Slack 선택 → xoxb, xapp, 내 U… 아이디)
hermes gateway setup

# 4. 플러그인 설치
python scripts\install.py alice

# 5. 상시 실행 등록 후 재시작
hermes gateway install
hermes gateway restart
```

6. 슬랙에서 봇에게 DM을 보내 보고, `/hermes-alice help`를 쳐 봅니다.

**반드시 나만 허용하세요.** 허용 사용자(`SLACK_ALLOWED_USERS`)에는 내 멤버 ID만 넣습니다.

## 이미 기본 방식으로 만든 앱이 있다면

1번을 내 아이디로 다시 실행한 뒤, 내 앱의 *Features → App Manifest → Edit* 에서 내용을 교체하고 *Save* → 재설치합니다. 그다음 4·5번을 하면 됩니다. 이름이 안 바뀌면 *Basic Information → Display Information* 과 *App Home* 의 이름도 확인합니다.

## 전달 메시지 읽기 (선택)

슬랙의 **메시지 전달**로 보낸 내용이 빈 메시지처럼 보이는 경우, 선택 플러그인 `slack-forwarded`를 설치합니다.

```powershell
# 기존 봇: 다른 플러그인과 슬래시 명령 설정은 그대로 유지
python scripts\install.py --forwarded-only

# 신규 설치 때 함께 추가하려면
python scripts\install.py alice --with-forwarded
```

설치 프로그램은 게이트웨이를 재시작하지 않습니다. 적용할 준비가 된 뒤에만 별도로 `hermes gateway restart`를 실행합니다. 전달 원문은 작성자·출처 채널 ID·퍼머링크와 함께 **신뢰되지 않은 인용문**으로 표시되며, 현재 발신자의 명령으로 취급하지 않습니다. 추가 Slack 권한이나 원본 채널 조회가 필요 없고, 일반 메시지 링크 미리보기는 중복 추가하지 않습니다.

인용 하나는 최대 4,000자, 한 메시지의 전달 인용은 최대 5개·총 8,000자로 제한됩니다. 기본 어댑터의 비공개 메서드를 사용하는 호환성 보완이므로 Hermes 업데이트 뒤 통합 테스트를 다시 실행해야 합니다. 해제는 `hermes plugins disable slack-forwarded` 후 준비된 시점에 게이트웨이를 재시작합니다. 플러그인 비활성화만으로 이미 실행 중인 어댑터 래퍼가 제거되지는 않습니다. [영문 상세·검증 방법](slack-forwarded.md)

## 모델 전환 알림 (선택)

`fallback-alert` 플러그인은 Hermes가 한도·장애로 다른 모델로 넘어가거나 돌아올 때, 또는 같은 서비스 안에서 다른 계정으로 넘어갈 때 슬랙 홈 채널로 한 번 알려 줍니다. 계정 이름을 알아보기 쉽게 하려면 Hermes `.env`(`hermes config env-path`로 위치 확인)에 다음을 넣습니다.

```
FALLBACK_ALERT_ACCOUNT_NAMES=personal=개인,anthropic-oauth-2=회사
```

필요 없으면 `python scripts\install.py alice --no-alert` 로 설치하거나 `hermes plugins disable fallback-alert` 로 끕니다.
