# GDCampReserv

강동캠핑 예약 페이지(`https://camp.xticket.kr/`)를 대상으로 한 자동화 코드 모음입니다.  
현재 저장소에는 브라우저 확장 프로그램 버전(`JS`)과 Playwright 기반 Python 버전(`python`)이 함께 들어 있습니다.

## 폴더 구성

| 경로 | 용도 | 비고 |
| --- | --- | --- |
| `JS/` | Chrome Manifest V3 기반 확장 프로그램 | Tesseract.js로 CAPTCHA를 읽고, 페이지 내 Knockout ViewModel을 직접 제어 |
| `JS/assets/` | 알림 사운드 등 정적 리소스 | `tada.mp3` 포함 |
| `JS/images/` | 확장 프로그램 버튼/아이콘 이미지 | 시작/정지 버튼, 아이콘 |
| `python/` | Playwright 기반 자동 예약 스크립트와 OCR 관련 코드 | 현재 실사용 엔트리포인트는 `gdcamp_macro.py` |
| `python/models/` | Python OCR 모델 산출물 저장 폴더 | `digit_ocr_model.npz` 포함 |

## JS 폴더

`JS` 폴더는 강동캠핑 사이트용 브라우저 확장 프로그램입니다.

- `manifest.json`: 대상 도메인을 `https://camp.xticket.kr/*`로 제한한 확장 프로그램 설정 파일입니다.
- `content.js`: 페이지 상단에 월/일/시설/사이트 입력 UI와 시작/정지 버튼을 주입하고, 세션 스토리지에 매크로 상태를 저장합니다.
- `injectedScript.js`: 페이지 내부 Knockout ViewModel을 이용해 날짜 선택, 시설 전환, 사이트 선택, 빈자리 순환 탐색, 예약 제출을 처리합니다.
- `background.js`: 예약 성공 시 텔레그램 메시지를 보내는 백그라운드 서비스 워커입니다.
- `options.html`, `options.js`: 텔레그램 봇 토큰과 채팅 ID를 저장하는 설정 화면입니다.
- `jquery-3.7.0.min.js`, `tesseract.min.js`, `worker.min.js`: 확장 프로그램에서 사용하는 번들 라이브러리입니다.

참고로 `JS/README.md`와 일부 화면 문구에는 SRT Macro 기반에서 가져온 레거시 설명이 남아 있습니다. 현재 코드 기준 실제 대상은 강동캠핑 예약 페이지입니다.

## Python 폴더

`python` 폴더는 JS 플로우를 Playwright로 옮긴 자동화 버전과 OCR 실험 코드를 포함합니다.

- `gdcamp_macro.py`: 메인 예약 매크로입니다. 월/일 선택, 시설/사이트 선택, CAPTCHA 캡처, OCR 판독, 입력/확정, 실패 시 재시도를 한 흐름으로 수행합니다.
- `digit_ocr.py`: 숫자 CAPTCHA용 OCR 모델 학습/예측 CLI입니다.
- `train_classifier.py`: 참조 이미지로 `models/digit_ocr_model.npz`를 생성하고 샘플 이미지를 테스트하는 간단한 스크립트입니다.

## 빠른 실행

### JS 확장 프로그램

1. Chrome 확장 프로그램 관리 페이지를 엽니다.
2. 개발자 모드를 켭니다.
3. `압축해제된 확장 프로그램을 로드`에서 `JS/` 폴더를 선택합니다.
4. 강동캠핑 예약 페이지에 접속한 뒤 확장 UI에서 목표 월/일, 시설, 사이트를 설정합니다.

### Python 매크로

PowerShell 기준 예시는 아래와 같습니다.

```powershell
cd python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
python .\gdcamp_macro.py --target-month 4 --target-day 19 --area-name 2 --site-no 6
```

주요 옵션은 다음과 같습니다.

- `--site-no > 0`: 고정 사이트 예약
- `--site-no <= 0`: 빈자리 순환 탐색
- `--telegram-bot-token`, `--telegram-chat-id`: 알림 전송
- `--login-id`, `--login-pw`: 자동 로그인
- `--captcha-model-path`: 학습된 OCR 모델 경로
- `--headless`: 브라우저 없이 실행
