# GDCampReserv JS

강동캠핑 예약 사이트(`https://camp.xticket.kr/`)용 Chrome 확장 프로그램입니다.  
페이지 상단에 매크로 UI를 주입하고, Knockout ViewModel을 직접 제어해 날짜/시설/사이트 선택과 예약 제출을 자동화합니다.

## 대상 범위

- Manifest 버전: Chrome Extension Manifest V3
- 대상 URL: `https://camp.xticket.kr/*`
- 기본 진입 페이지: `https://camp.xticket.kr/web/main`

## 주요 기능

- 예약 페이지 헤더에 월, 일, 시설, 사이트 입력창과 시작/정지 버튼을 주입합니다.
- `sessionStorage`에 설정값을 저장해 새로고침 후에도 매크로 상태를 이어갑니다.
- 시설 코드는 `0=가족캠핑장`, `1=오토캠핑장`, `2=매화나무캠핑장`으로 처리합니다.
- `siteNo > 0`이면 지정한 사이트를 선택하고, `siteNo <= 0`이면 빈자리를 순환 탐색합니다.
- CAPTCHA 레이어가 열리면 이미지(`div.ex_area img`)를 캔버스로 캡처하고 `Tesseract.js`로 숫자를 인식합니다.
- `400 Bad Request` 페이지가 열리면 즉시 새로고침하고, 정상 페이지에서도 10분 주기로 새로고침합니다.
- 옵션 페이지에 저장한 텔레그램 봇 토큰/채팅 ID가 있으면 알림 메시지를 전송합니다.

## 파일 구성

| 파일 | 역할 |
| --- | --- |
| `manifest.json` | 권한, 콘텐츠 스크립트, 서비스 워커, 옵션 페이지를 정의합니다. |
| `content.js` | UI 주입, 매크로 시작/정지, CAPTCHA 이미지 캡처, OCR 호출을 담당합니다. |
| `injectedScript.js` | 페이지 내부 Knockout ViewModel을 사용해 날짜 선택, 시설 전환, 사이트 클릭, 예약 제출을 처리합니다. |
| `background.js` | 텔레그램 메시지 전송 로직을 처리합니다. |
| `options.html` / `options.js` | 텔레그램 Bot Token, Chat ID 저장 화면입니다. |
| `assets/tada.mp3` | 알림 사운드 파일입니다. |
| `images/*` | 시작/정지 버튼과 확장 아이콘 이미지입니다. |
| `jquery-3.7.0.min.js` | DOM 조작용 라이브러리입니다. |
| `tesseract.min.js`, `worker.min.js` | CAPTCHA OCR용 Tesseract.js 번들입니다. |

## 설치

1. Chrome에서 `chrome://extensions`를 엽니다.
2. 우측 상단의 개발자 모드를 켭니다.
3. `압축해제된 확장 프로그램을 로드`를 눌러 `JS/` 폴더를 선택합니다.
4. 텔레그램 알림을 사용할 경우 확장 프로그램 옵션에서 Bot Token과 Chat ID를 저장합니다.

## 사용 방법

1. 강동캠핑 예약 페이지에 로그인한 뒤 메인 화면으로 이동합니다.
2. 헤더에 추가된 입력창에서 월, 일, 시설, 사이트 번호를 설정합니다.
3. 시작 버튼을 누르면 페이지가 새로고침되며 매크로가 동작합니다.
4. 지정 사이트 모드에서는 해당 시설의 특정 사이트를 바로 선택합니다.
5. 빈자리 탐색 모드에서는 시설을 순환하면서 예약 가능한 사이트를 찾습니다.
6. CAPTCHA가 나타나면 이미지를 읽어 자동 입력 후 예약 확정을 시도합니다.
7. 중지 버튼을 누르면 매크로 플래그를 제거하고 페이지를 다시 로드합니다.

## 주의 사항

- 이 확장 프로그램은 사이트 내부 Knockout ViewModel 이름과 DOM 구조에 강하게 의존합니다. 사이트가 바뀌면 `content.js`와 `injectedScript.js`를 같이 수정해야 합니다.
- `options.html` 제목 등 일부 UI 문자열에는 이전 SRT Macro 기반 흔적이 남아 있습니다.
