# Python 버전 (JS 플로우 포팅)

기존 `JS/content.js` + `JS/injectedScript.js` 동작 플로우를 Python으로 옮긴 매크로입니다.

## 변경점
- OCR 엔진을 `tesseract`에서 `CaptchaCracker`로 교체.
- Knockout ViewModel 제어는 Playwright의 `page.evaluate()`로 동일하게 수행.

## 설치
```bash
cd python
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## 실행
```bash
python gdcamp_macro.py \
  --target-month 4 \
  --target-day 19 \
  --area-name 2 \
  --site-no 6
```

### 옵션
- `--site-no > 0`: 고정 사이트 예약
- `--site-no <= 0`: 빈자리 순환 탐색 모드
- `--telegram-bot-token`, `--telegram-chat-id`: 알림 전송
- `--headless`: 헤드리스 실행

## 플로우 매핑
1. 목표 월/일 선택
2. 시설/사이트 선택(또는 빈자리 탐색)
3. 예약 버튼 클릭
4. CAPTCHA 이미지 캡처
5. `CaptchaCracker`로 OCR
6. CAPTCHA 입력 + 예약 확정 클릭
7. 실패 시 reload 후 재시도

> 참고: 사이트 UI/뷰모델 구조가 변경되면 evaluate 내부 JS 셀렉터/속성명을 업데이트해야 합니다.
