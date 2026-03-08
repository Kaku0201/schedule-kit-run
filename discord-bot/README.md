# discord-bot

`일정 추합 시트` 구글시트의 `참여인원저장` 시트를 읽어와  
새로 추가된 일정이 있을 때 디스코드 채널로 자동 전송하는 선택형 알림 도구입니다.

이 문서는 **아예 처음 설정하는 사람 기준**으로,  
GitHub 업로드부터 Discord 봇 생성, Google 서비스 계정 생성, GitHub Actions 설정까지 한 번에 설명합니다.

## 준비물

사용 전 아래 정보가 필요합니다.

- GitHub 계정
- Discord 계정
- Google 계정
- 구글시트 사본
- 디스코드 서버에서 봇을 추가할 권한

## 파일 구성

- `bot.py` : 시트를 읽고 디스코드로 보내는 코드
- `requirements.txt` : 필요한 라이브러리 목록
- `README.md` : 사용 안내 문서
- `.github/workflows/` : GitHub Actions 실행 파일

## 전체 진행 순서

1. 이 레포를 복사하거나 다운로드합니다.
2. GitHub에 새 저장소를 만들고 파일을 업로드합니다.
3. Discord 봇을 만듭니다.
4. Discord 채널 ID를 확인합니다.
5. Google Cloud에서 서비스 계정을 만듭니다.
6. Google Sheets API를 활성화합니다.
7. 서비스 계정 키(JSON)를 생성합니다.
8. 구글시트를 서비스 계정 이메일과 공유합니다.
9. GitHub Secrets를 등록합니다.
10. GitHub Actions를 실행합니다.

## 1. GitHub 저장소 만들기

1. GitHub에서 새 저장소를 만듭니다.
2. 이 폴더의 파일을 업로드합니다.
3. 아래 파일들이 들어있는지 확인합니다.

- `discord-bot/bot.py`
- `discord-bot/requirements.txt`
- `discord-bot/.env.example`
- `.github/workflows/`

## 2. Discord 봇 만들기

1. Discord 개발자 포털에서 새 애플리케이션을 만듭니다.
2. Bot 메뉴에서 봇을 생성합니다.
3. 봇 토큰을 복사합니다.
4. OAuth2 / URL Generator에서 봇 초대 링크를 만듭니다.
5. 봇을 사용할 서버에 초대합니다.

## 3. Discord 채널 ID 확인하기

1. Discord 설정에서 개발자 모드를 켭니다.
2. 메시지를 보낼 채널을 우클릭합니다.
3. `채널 ID 복사`를 선택합니다.

## 4. 구글시트 ID 확인하기

사용 중인 구글시트 주소에서 시트 ID를 복사합니다.

예시 주소:

`https://docs.google.com/spreadsheets/d/여기가시트ID/edit`

## 5. Google 서비스 계정 만들기

1. Google Cloud 콘솔에서 프로젝트를 만듭니다.
2. 서비스 계정을 생성합니다.
3. 서비스 계정 이메일을 확인합니다.

## 6. Google Sheets API 활성화

1. Google Cloud 콘솔에서 API 라이브러리로 이동합니다.
2. **Google Sheets API**를 활성화합니다.

## 7. 서비스 계정 키(JSON) 만들기

1. 만든 서비스 계정으로 들어갑니다.
2. 키 생성 메뉴에서 JSON 키를 생성합니다.
3. 다운로드한 JSON 내용을 보관합니다.

## 8. 구글시트 공유 설정

1. 사용 중인 구글시트를 엽니다.
2. 공유 버튼을 누릅니다.
3. 서비스 계정 이메일을 추가합니다.
4. 보기 권한 이상으로 공유합니다.

## 9. GitHub Secrets 등록하기

GitHub 저장소에서 **Settings → Secrets and variables → Actions**로 들어가 아래 값을 등록합니다.

### 필수 Secrets

1. Secrets 등록

레포 Settings → Secrets and variables → Actions 에 아래 5개 추가

- DISCORD_BOT_TOKEN
- DISCORD_CHANNEL_ID
- GOOGLE_SHEET_ID
- GOOGLE_WORKSHEET_NAME
- GOOGLE_SERVICE_ACCOUNT_JSON

2. Actions 권한 확인

레포 Settings → Actions → General에서
Workflow permissions -> Read and write permissions
sent_records.json 커밋이 가능해.

### 값 설명

- `DISCORD_BOT_TOKEN`  
  Discord 개발자 포털에서 만든 봇 토큰

- `DISCORD_CHANNEL_ID`  
  메시지를 보낼 채널 ID

- `GOOGLE_SHEET_ID`  
  구글시트 주소의 시트 ID

- `GOOGLE_WORKSHEET_NAME`  
  읽어올 워크시트 이름  
  기본값: `참여인원저장`

- `GOOGLE_SERVICE_ACCOUNT_JSON`  
  서비스 계정 JSON 파일 전체 내용을 한 줄 문자열로 넣은 값

## 10. GitHub Actions 실행하기

1. 저장소의 Actions 탭으로 이동합니다.
2. 워크플로가 보이는지 확인합니다.
3. 필요하면 수동 실행합니다.
4. 이후에는 설정한 주기마다 자동으로 실행됩니다.

## 작동 방식

1. 구글시트에서 일정 확정 시간을 입력합니다.
2. `참여인원저장` 시트에 날짜, 요일, 시간, 참여 인원이 저장됩니다.
3. GitHub Actions가 일정 간격으로 시트를 확인합니다.
4. 이전에 보내지 않은 새 일정이 있으면 디스코드 채널로 전송합니다.

## 주의사항

- 이 도구는 시트 사용에 필수가 아닙니다.
- 디스코드 알림이 필요한 경우에만 설정해서 사용하면 됩니다.
- GitHub에 올렸다고 바로 자동 실행되지는 않습니다.
- GitHub Secrets와 Actions 설정이 끝나야 정상 작동합니다.
- 서비스 계정 이메일이 시트에 공유되어 있지 않으면 시트를 읽지 못합니다.

## 자주 막히는 부분

### Discord 메시지가 안 보내지는 경우
- 봇 토큰이 잘못되었는지 확인
- 채널 ID가 맞는지 확인
- 봇이 해당 채널을 볼 수 있는지 확인

### 구글시트를 못 읽는 경우
- 시트 ID가 맞는지 확인
- 워크시트 이름이 맞는지 확인
- 서비스 계정 이메일이 시트에 공유되어 있는지 확인
- Google Sheets API가 활성화되어 있는지 확인

### GitHub Actions가 안 도는 경우
- Actions가 저장소에서 활성화되어 있는지 확인
- Secrets 이름이 코드와 정확히 같은지 확인
- workflow 파일 위치가 맞는지 확인

## 참고

이 도구는 **GitHub Actions를 사용해 주기적으로 실행하는 방식**을 기준으로 작성되었습니다.
