#!/usr/bin/env python3
"""Gangdong camp reservation macro (Python port of JS extension flow).

Flow parity goals:
- Select target month/day
- Select area/site (or rotate for available slot)
- Submit reservation
- Detect captcha image and solve OCR
- Fill captcha + confirm
- Retry/reload on transient failures
"""

from __future__ import annotations

import argparse
import base64
import inspect
import os
import random
import re
import time
from datetime import datetime
from hashlib import sha1
from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import BrowserContext, Page, sync_playwright

import cv2
import numpy as np
from digit_ocr import load_digit_model, predict_digit_string


@dataclass
class MacroConfig:
    target_month: int = 3
    target_day: int = 26
    area_name: int = 2 # 0: family, 1: auto, 2: plum
    site_no: int = 0   # >0 fixed seat, <=0 scan for available
    reload_interval_s: int = 600
    initial_url: str = "https://camp.xticket.kr/web/main?shopEncode=5f9422e223671b122a7f2c94f4e15c6f71cd1a49141314cf19adccb98162b5b0"
    headless: bool = False
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    captcha_dump_dir: Optional[str] = None
    captcha_model_path: str = None
    verbose: bool = False
    captcha_max_attempts_per_reservation: int = 8



def debug_log(cfg: Optional[MacroConfig], message: str) -> None:
    if cfg is not None and cfg.verbose:
        print(f"[DEBUG] {message}")

class CaptchaCrackerAdapter:
    def __init__(self, verbose: bool = False, model_path: str = None, max_length: int = 4) -> None:
        self._verbose = verbose
        self._log(f"load model={model_path}")
        self._AM = load_digit_model(model_path)
        self._max_length = max_length

    def _log(self, msg: str) -> None:
        if self._verbose:
            print(f"[DEBUG][OCR] {msg}")

    def solve_bytes(self, image_bytes: bytes) -> str:
        self._log(f"solve_bytes start size={len(image_bytes)}")
        if not image_bytes:
            return ""

        try:
            result = predict_digit_string(
                image_bytes=image_bytes,
                digit_count=self._max_length,
                model=self._AM,
            )
            text = result.text
#            text = self._AM.predict_from_bytes(image_bytes)
        except Exception as exc:  # noqa: BLE001
            self._log(f"predict_from_bytes failed: {exc}")
            return ""

        normalized = re.sub(r"\D", "", str(text or ""))
        self._log(f"solve_bytes result raw={text!r} normalized={normalized!r}")
        return normalized


def guess_image_extension(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return ".webp"
    return ".bin"


def dump_captcha_image(captcha_bytes: bytes, dump_dir: Optional[str]) -> Optional[str]:
    if not dump_dir:
        return None
    try:
        os.makedirs(dump_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        ext = guess_image_extension(captcha_bytes)
        path = os.path.join(dump_dir, f"captcha_{timestamp}{ext}")
        with open(path, "wb") as f:
            f.write(captcha_bytes)
        return path
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] captcha dump 저장 실패: {exc}")
        return None

def send_telegram(bot_token: Optional[str], chat_id: Optional[str], msg: str) -> None:
    if not bot_token or not chat_id:
        return

    import urllib.parse
    import urllib.request

    base = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    query = urllib.parse.urlencode({"chat_id": chat_id, "text": msg})
    url = f"{base}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            resp.read()
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Telegram send failed: {exc}")


def js_wait_for_knockout(page: Page, timeout_ms: int = 15000) -> None:
    """Wait until Knockout view model is available.

    Avoid Playwright's `wait_for_function` here because some target pages can
    monkey-patch globals used by Playwright's injected selector runtime,
    causing runtime errors like `this._engines.set is not a function`.
    """
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            ready = page.evaluate(
                """
                () => {
                  try {
                    return typeof ko !== 'undefined' && !!ko.dataFor(document.body);
                  } catch (e) {
                    return false;
                  }
                }
                """
            )
        except Exception:  # noqa: BLE001
            ready = False

        if ready:
            return
        time.sleep(0.1)

    raise TimeoutError("Knockout view model was not ready in time")


def js_change_month_and_select_day(page: Page, target_month: int, target_day: int) -> bool:
    return bool(
        page.evaluate(
            """
            ({targetMonth, targetDay}) => {
              function pad(str, max){
                str = String(str);
                return str.length < max ? pad("0" + str, max) : str;
              }
              const vm = ko.dataFor(document.body);
              if (!vm || !vm.currentMonth || !vm.monthCalendar || !vm.clickBookDate) return false;

              const currentMonth = new Date().getFullYear() + pad(targetMonth, 2);
              vm.currentMonth(currentMonth);

              let found = null;
              vm.monthCalendar().forEach((week) => {
                week().forEach((day) => {
                  if (pad(day().dateLabel, 2) === pad(targetDay, 2)) {
                    found = day;
                  }
                });
              });
              if (!found) return false;
              vm.clickBookDate(found());
              return true;
            }
            """,
            {"targetMonth": target_month, "targetDay": target_day},
        )
    )


def js_ensure_month_and_day_selected(page: Page, target_month: int, target_day: int) -> bool:
    return bool(
        page.evaluate(
            """
            ({targetMonth, targetDay}) => {
              function pad(str, max){
                str = String(str);
                return str.length < max ? pad("0" + str, max) : str;
              }
              function readObservable(value) {
                return typeof value === 'function' ? value() : value;
              }
              function isSelectedValue(value) {
                return value === true || value === '1' || value === 1 || value === 'Y' || value === 'y';
              }

              const vm = ko.dataFor(document.body);
              if (!vm || !vm.currentMonth || !vm.monthCalendar || !vm.clickBookDate) return false;

              const expectedMonth = String(new Date().getFullYear()) + pad(targetMonth, 2);
              const currentMonth = String(readObservable(vm.currentMonth) ?? "");

              let found = null;
              let daySelected = false;

              vm.monthCalendar().forEach((week) => {
                week().forEach((day) => {
                  const dayValue = day();
                  if (pad(dayValue.dateLabel, 2) !== pad(targetDay, 2)) return;
                  found = day;

                  if (
                    isSelectedValue(dayValue.select_yn) ||
                    isSelectedValue(dayValue.choice_yn) ||
                    isSelectedValue(dayValue.selected) ||
                    isSelectedValue(dayValue.isSelected) ||
                    isSelectedValue(dayValue.active)
                  ) {
                    daySelected = true;
                  }
                });
              });

              const selectedDateCandidates = [
                vm.currentBookDate,
                vm.currentDate,
                vm.selectedDate,
                vm.selectedBookDate,
              ];

              for (const candidate of selectedDateCandidates) {
                const value = readObservable(candidate);
                if (value == null) continue;

                if (typeof value === 'object') {
                  if (pad(value.dateLabel, 2) === pad(targetDay, 2)) {
                    daySelected = true;
                    break;
                  }
                  continue;
                }

                const text = String(value);
                if (
                  text === String(targetDay) ||
                  text === pad(targetDay, 2) ||
                  text.endsWith(`-${pad(targetMonth, 2)}-${pad(targetDay, 2)}`) ||
                  text.endsWith(`/${pad(targetMonth, 2)}/${pad(targetDay, 2)}`) ||
                  text.endsWith(`${pad(targetMonth, 2)}${pad(targetDay, 2)}`)
                ) {
                  daySelected = true;
                  break;
                }
              }

              if (currentMonth === expectedMonth && daySelected) {
                return true;
              }

              vm.currentMonth(expectedMonth);

              found = null;
              vm.monthCalendar().forEach((week) => {
                week().forEach((day) => {
                  const dayValue = day();
                  if (pad(dayValue.dateLabel, 2) === pad(targetDay, 2)) {
                    found = day;
                  }
                });
              });

              if (!found) return false;
              vm.clickBookDate(found());
              return true;
            }
            """,
            {"targetMonth": target_month, "targetDay": target_day},
        )
    )


def js_select_site(page: Page, area_name: int, site_no: int) -> bool:
    return bool(
        page.evaluate(
            """
            ({areaName, siteNo}) => {
              function pad(str, max){
                str = String(str);
                return str.length < max ? pad("0" + str, max) : str;
              }
              const vm = ko.dataFor(document.body);
              if (!vm || !vm.currentProductGroupCode || !vm.products || !vm.clickProduct) return false;

              vm.currentProductGroupCode(pad(Number(areaName) + 1, 4));
              const products = vm.products();
              if (!products || siteNo <= 0 || siteNo > products.length) return false;
              vm.clickProduct(products[siteNo - 1]);
              return true;
            }
            """,
            {"areaName": area_name, "siteNo": site_no},
        )
    )


def js_scan_and_select_available(page: Page, target_month: int, target_day: int, max_cycles: int = 300) -> bool:
    for idx in range(max_cycles):
        if not js_ensure_month_and_day_selected(page, target_month, target_day):
            time.sleep(0.2 + random.random() * 0.1)
            continue

        area_code = idx%3+1
#        area_code = random.randint(1, 3)
        selected = bool(
            page.evaluate(
                """
                ({areaCode}) => {
                  function pad(str, max){
                    str = String(str);
                    return str.length < max ? pad("0" + str, max) : str;
                  }
                  const vm = ko.dataFor(document.body);
                  if (!vm || !vm.currentProductGroupCode || !vm.products || !vm.clickProduct) return false;

                  vm.currentProductGroupCode(pad(areaCode, 4));
                  const list = vm.products();
                  if (!list || !list.length) return false;

                  let site = null;
                  list.some((x) => {
                    if (x.select_yn === '1' && x.status_code === '0') {
                      site = x;
                      return true;
                    }
                    return false;
                  });

                  if (!site) return false;
                  vm.clickProduct(site);
                  return true;
                }
                """,
                {"areaCode": area_code},
            )
        )
        if selected:
            return True
        time.sleep(0.2 + random.random() * 0.1)
    return False


def js_click_reservation(page: Page) -> bool:
    return bool(
        page.evaluate(
            """
            () => {
              const vm = ko.dataFor(document.body);
              if (!vm || !vm.clickReservation) return false;
              vm.clickReservation();
              return true;
            }
            """
        )
    )


def js_fill_captcha_and_confirm(page: Page, captcha_text: str) -> bool:
    return bool(
        page.evaluate(
            """
            ({captchaText}) => {
              const vm = ko.dataFor(document.body);
              if (!vm || !vm.captcha || !vm.clickReservationConfirm) return false;
              vm.captcha(String(captchaText).replace(/\s+/g, ''));
              vm.clickReservationConfirm();
              return true;
            }
            """,
            {"captchaText": captcha_text},
        )
    )


def wait_and_capture_captcha(
    page: Page,
    timeout_ms: int = 10000,
    previous_signature: Optional[str] = None,
    min_bytes: int = 200,
) -> tuple[Optional[bytes], Optional[str]]:
    """Capture captcha image bytes without Playwright locator APIs.

    Returns image bytes and signature. If `previous_signature` is provided,
    waits for a different captcha image before returning.
    """
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            capture = page.evaluate(
                """
                () => {
                  const candidates = Array.from(document.querySelectorAll('div.ex_area img'));
                  if (!candidates.length) return null;

                  let target = null;
                  let bestArea = 0;
                  candidates.forEach((img) => {
                    const style = window.getComputedStyle(img);
                    const visible =
                        style.display !== 'none' &&
                        style.visibility !== 'hidden' &&
                        Number(style.opacity || '1') > 0 &&
                        (img.offsetWidth > 0 || img.offsetHeight > 0);
                    if (!visible || !img.complete) return;

                    const width = img.naturalWidth || img.width || 0;
                    const height = img.naturalHeight || img.height || 0;
                    const area = width * height;
                    if (area > bestArea) {
                      bestArea = area;
                      target = img;
                    }
                  });

                  if (!target) return null;
                  const width = target.naturalWidth || target.width;
                  const height = target.naturalHeight || target.height;
                  if (!width || !height || width < 80 || height < 20) return null;

                  const canvas = document.createElement('canvas');
                  canvas.width = width;
                  canvas.height = height;
                  const ctx = canvas.getContext('2d');
                  if (!ctx) return null;
                  ctx.drawImage(target, 0, 0, width, height);
                  return {
                    dataUrl: canvas.toDataURL('image/png'),
                    width,
                    height,
                    src: target.currentSrc || target.getAttribute('src') || '',
                  };
                }
                """
            )
        except Exception:  # noqa: BLE001
            capture = None

        data_url = capture.get('dataUrl') if isinstance(capture, dict) else None
        if data_url and isinstance(data_url, str) and data_url.startswith('data:image/') and ';base64,' in data_url:
            try:
                image_bytes = base64.b64decode(data_url.split(',', 1)[1])
                signature = sha1(image_bytes).hexdigest()
                if previous_signature and signature == previous_signature:
                    time.sleep(0.1)
                    continue

                if len(image_bytes) < min_bytes:
                    time.sleep(0.1)
                    continue

                img_array = np.frombuffer(image_bytes, dtype=np.uint8)
                decoded = cv2.imdecode(img_array, cv2.IMREAD_GRAYSCALE)
                if decoded is None:
                    time.sleep(0.1)
                    continue

                height, width = decoded.shape[:2]
                if width < 80 or height < 20:
                    time.sleep(0.1)
                    continue

                return image_bytes, signature

            except Exception:  # noqa: BLE001
                return None, None

        time.sleep(0.1)

    return None, None

def dummy_call(page: Page) -> None:
    page.evaluate(
        """
        () => {
          const img = document.querySelector('div.ex_area img');
        }
        """
    )

    return None




def install_js_runtime_guards(context: BrowserContext) -> None:
    """Guard native constructors from page-side monkey patching.

    Some target pages overwrite built-in constructors (e.g. `Map`/`Set`).
    Playwright utility scripts rely on these natives while parsing evaluation
    results, which can trigger errors such as `refs.set is not a function`.
    """
    context.add_init_script(
        """
        (() => {
          const g = globalThis;
          const keep = {
            Map: g.Map,
            Set: g.Set,
            WeakMap: g.WeakMap,
            WeakSet: g.WeakSet,
          };

          for (const [name, value] of Object.entries(keep)) {
            try {
              Object.defineProperty(g, name, {
                value,
                writable: false,
                configurable: false,
                enumerable: false,
              });
            } catch (e) {
              // ignore
            }
          }
        })();
        """
    )

def ensure_page(context: BrowserContext, cfg: MacroConfig) -> Page:
    page = context.new_page()
    page.goto(cfg.initial_url, wait_until="domcontentloaded")
    return page

@dataclass
class DialogTracker:
    count: int = 0
    last_message: Optional[str] = None
    last_seen_at: float = 0.0


def bind_dialog_auto_accept(page: Page, tracker: DialogTracker, cfg: MacroConfig) -> None:
    def _on_dialog(dialog) -> None:
        tracker.count += 1
        tracker.last_message = dialog.message
        tracker.last_seen_at = time.time()
        debug_log(
            cfg,
            f"dialog detected count={tracker.count} message={tracker.last_message} time={tracker.last_seen_at:.3f}"
        )
        dialog.accept()

    page.on("dialog", _on_dialog)


def has_new_dialog_since(tracker: DialogTracker, submitted_at: float) -> bool:
    return tracker.last_seen_at >= submitted_at




def is_known_playwright_eval_runtime_error(exc: Exception) -> bool:
    msg = str(exc)
    return (
        "refs.set is not a function" in msg
        or "this._engines.set is not a function" in msg
    )

def run_macro(cfg: MacroConfig) -> None:
    cracker = CaptchaCrackerAdapter(verbose=cfg.verbose, model_path=cfg.captcha_model_path)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=cfg.headless)
        context = browser.new_context()
        install_js_runtime_guards(context)
        page = ensure_page(context, cfg)
        dialog_tracker = DialogTracker()
        bind_dialog_auto_accept(page, dialog_tracker, cfg)

        print("[INFO] 로그인 완료 상태를 확인한 뒤 엔터를 누르세요.")
        input()

        last_reload = time.time()

        while True:
            try:
                if time.time() - last_reload > cfg.reload_interval_s:
                    page.reload(wait_until="domcontentloaded")
                    last_reload = time.time()

                debug_log(cfg, "waiting for knockout view model")
                js_wait_for_knockout(page)
                debug_log(cfg, "knockout ready")

                debug_log(cfg, f"select month/day start month={cfg.target_month} day={cfg.target_day}")
                ok = js_change_month_and_select_day(page, cfg.target_month, cfg.target_day)
                debug_log(cfg, f"select month/day result={ok}")
                if not ok:
                    print("[WARN] 날짜 탐색 실패 -> reload")
                    last_reload = time.time()
                    page.reload(wait_until="domcontentloaded")
                    continue

                time.sleep(0.2)

                if cfg.site_no > 0:
                    debug_log(cfg, f"fixed site mode area={cfg.area_name} site={cfg.site_no}")
                    ok = js_select_site(page, cfg.area_name, cfg.site_no)
                else:
                    debug_log(cfg, "scan mode for available site")
                    ok = js_scan_and_select_available(page, cfg.target_month, cfg.target_day)
                debug_log(cfg, f"site selection result={ok}")

                if not ok:
                    print("[WARN] 빈 자리 확인 불가 -> reload")
                    last_reload = time.time()
                    page.reload(wait_until="domcontentloaded")
                    continue

                time.sleep(0.2)

                if not js_click_reservation(page):
                    print("[WARN] 예약 클릭 실패 -> reload")
                    last_reload = time.time()
                    page.reload(wait_until="domcontentloaded")
                    continue

                captcha_solved = False
                last_captcha_signature: Optional[str] = None
                for captcha_attempt in range(1, cfg.captcha_max_attempts_per_reservation + 1):
                    debug_log(cfg, f"capturing captcha image attempt={captcha_attempt}")
                    captcha_bytes, captcha_signature = wait_and_capture_captcha(
                        page,
                        previous_signature=last_captcha_signature,
                    )
                    debug_log(cfg, f"captcha bytes captured={0 if not captcha_bytes else len(captcha_bytes)}")
                    if not captcha_bytes:
                        print("[WARN] captcha 이미지 대기 실패 -> reload")
                        last_reload = time.time()
                        page.reload(wait_until="domcontentloaded")
                        break

                    dump_path = dump_captcha_image(captcha_bytes, cfg.captcha_dump_dir)
                    if dump_path:
                        print(f"[INFO] captcha image saved: {dump_path}")

                    debug_log(cfg, "ocr solving start")
                    captcha_text = cracker.solve_bytes(captcha_bytes)
                    debug_log(cfg, f"ocr solving done text_len={len(captcha_text) if captcha_text else 0}")
                    print(f"[INFO] captcha text: {captcha_text}")

                    if not captcha_text:
                        print("[WARN] captcha OCR empty -> 다음 captcha 재시도")
                        continue

                    submitted_at = time.time()
                    debug_log(cfg, "submit captcha text to page")
                    ok = js_fill_captcha_and_confirm(page, captcha_text)
                    debug_log(cfg, f"captcha confirm click result={ok}")
                    if not ok:
                        print("[WARN] captcha confirm 실패 -> reload")
                        last_reload = time.time()
                        page.reload(wait_until="domcontentloaded")
                        break

                    # 오답이면 alert(dialog) 발생 후 페이지가 새 captcha를 제공함.
                    max_wait = 2.0
                    start_wait = time.time()
                    detected = False
                    while time.time() - start_wait < max_wait:
                        dummy_call(page)
                        if has_new_dialog_since(dialog_tracker, submitted_at):
                            detected = True
                            break
                        time.sleep(0.1)


                    last_captcha_signature = captcha_signature
                    if detected:
                        print(f"[WARN] captcha 오답 alert 감지 -> 재시도 (msg: {dialog_tracker.last_message})")
                        continue


                    print("[INFO] captcha 입력 및 confirm 완료")
                    time.sleep(3)
                    captcha_solved = True
                    break

                if not captcha_solved:
                    print("[WARN] captcha 최대 재시도 초과 또는 처리 실패 -> 메인 루프 재시작")
                    continue
                else:
                    send_telegram(cfg.telegram_bot_token, cfg.telegram_chat_id, "Check Gangdong reservation.")
                    print("[INFO] 예약 성공")
                    break

            except KeyboardInterrupt:
                print("[INFO] 사용자 중단")
                break
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] 예외 발생: {exc} -> reload")
                debug_log(cfg, f"exception type={type(exc).__name__}")
                try:
                    if is_known_playwright_eval_runtime_error(exc):
                        print("[WARN] Playwright evaluate runtime 오염 감지 -> context 재생성")
                        context.close()
                        context = browser.new_context()
                        install_js_runtime_guards(context)
                        page = ensure_page(context, cfg)
                        dialog_tracker = DialogTracker()
                        bind_dialog_auto_accept(page, dialog_tracker, cfg)
                    else:
                        last_reload = time.time()
                        page.reload(wait_until="domcontentloaded")
                except Exception:  # noqa: BLE001
                    context.close()
                    context = browser.new_context()
                    install_js_runtime_guards(context)
                    page = ensure_page(context, cfg)
                    dialog_tracker = DialogTracker()
                    bind_dialog_auto_accept(page, dialog_tracker, cfg)

        context.close()
        browser.close()


'''
if __name__ == "__main__":
    args = MacroConfig(
#        verbose=True,
#        captcha_model_path="./models/digit_ocr_model.npz",
#        captcha_dump_dir="./"
    )
    run_macro(args)
'''

def parse_args() -> MacroConfig:
    parser = argparse.ArgumentParser(description="Gangdong reservation macro (Python)")
    parser.add_argument("--target-month", type=int, default=3, help="목표 월 (예: 4)")
    parser.add_argument("--target-day", type=int, default=28, help="목표 일 (예: 19)")
    parser.add_argument("--area-name", type=int, default=2, help="시설코드 0:가족 1:오토 2:매화")
    parser.add_argument("--site-no", type=int, default=6, help=">0 고정 사이트, <=0 빈자리 탐색")
    parser.add_argument("--reload-interval", type=int, default=600, help="주기적 새로고침(초)")
    parser.add_argument("--headless", action="store_true", help="헤드리스 실행")
    parser.add_argument("--telegram-bot-token", type=str, default=os.getenv("TELEGRAM_BOT_TOKEN"))
    parser.add_argument("--telegram-chat-id", type=str, default=os.getenv("TELEGRAM_CHAT_ID"))
    parser.add_argument("--captcha-model-path", type=str, default=os.getenv("CAPTCHA_MODEL_PATH"))
    parser.add_argument("--captcha-dump-path", type=str, default=None)
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--verbose", type=bool, default=False)
    args = parser.parse_args()

    return MacroConfig(
        target_month=args.target_month,
        target_day=args.target_day,
        area_name=args.area_name,
        site_no=args.site_no,
        reload_interval_s=args.reload_interval,
        headless=args.headless,
        telegram_bot_token=args.telegram_bot_token,
        telegram_chat_id=args.telegram_chat_id,
        captcha_model_path=args.captcha_model_path,
        captcha_max_attempts_per_reservation=args.max_attempts,
        verbose=args.verbose
    )


if __name__ == "__main__":
    run_macro(parse_args())
