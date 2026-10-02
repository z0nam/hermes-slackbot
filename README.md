# hermes-slackbot

> Kit for running your **personal [Hermes Agent](https://github.com/NousResearch/hermes-agent) as a Slack bot** in a workspace where other people run theirs too.
> Not affiliated with Nous Research.

한 슬랙 워크스페이스에서 여러 사람이 각자 자기 Hermes를 개인 봇으로 붙여 쓸 때 필요한 것들을 모은 키트입니다.

## 왜 필요한가

Hermes 기본 안내(`hermes slack manifest --agent-view --write`)대로 슬랙 앱을 만들면:

- 슬래시 명령 50여 개(`/hermes`, `/help`, `/new`, `/model` …)가 **전역으로** 등록됩니다. 같은 워크스페이스에 두 번째 사람이 설치하는 순간 명령이 겹치고, 나중에 설치한 앱이 명령을 가져갑니다.
- 앱 이름이 기본값 `Hermes`라서, 여러 개가 생기면 누구 봇인지 구분이 안 되고 공용 봇으로 오해받습니다.

이 키트는 사람마다 **`Hermes-<아이디>` 이름 + `/hermes-<아이디>` 명령 하나**로 정리해서 서로 겹치지 않게 합니다.

## 상태

초기 구성 중입니다. 내용은 PR로 들어옵니다.

## License

MIT
