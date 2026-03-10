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
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import BrowserContext, Page, sync_playwright


@dataclass
class MacroConfig:
    target_month: int
    target_day: int
    area_name: int  # 0: family, 1: auto, 2: plum
    site_no: int    # >0 fixed seat, <=0 scan for available
    reload_interval_s: int = 600
    initial_url: str = "https://camp.xticket.kr/web/main"
    headless: bool = False
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None


class CaptchaCrackerAdapter:
    """Wrapper to support multiple captchacracker API shapes."""

    def __init__(self) -> None:
        try:
            import captchacracker  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "captchacracker import failed. Install with: pip install captchacracker"
            ) from exc
        self._lib = captchacracker

    def solve_bytes(self, image_bytes: bytes) -> str:
        lib = self._lib

        # Variant A: captchacracker.CaptchaCracker().solve(...)
        if hasattr(lib, "CaptchaCracker"):
            cracker = lib.CaptchaCracker()
            if hasattr(cracker, "solve"):
                text = cracker.solve(image_bytes)
                return self._normalize(text)
            if hasattr(cracker, "predict"):
                text = cracker.predict(image_bytes)
                return self._normalize(text)

        # Variant B: captchacracker.solve(...)
        if hasattr(lib, "solve"):
            text = lib.solve(image_bytes)
            return self._normalize(text)

        # Variant C: captchacracker.crack(...)
        if hasattr(lib, "crack"):
            text = lib.crack(image_bytes)
            return self._normalize(text)

        raise RuntimeError("Unsupported captchacracker API shape")

    @staticmethod
    def _normalize(value: object) -> str:
        text = str(value) if value is not None else ""
        return re.sub(r"\s+", "", text)


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
    page.wait_for_function(
        """() => typeof ko !== 'undefined' && ko.dataFor(document.body)""",
        timeout=timeout_ms,
    )


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


def js_scan_and_select_available(page: Page, max_cycles: int = 300) -> bool:
    for _ in range(max_cycles):
        area_code = random.randint(1, 3)
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
        time.sleep(0.1 + random.random() * 0.2)
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


def wait_and_capture_captcha(page: Page, timeout_ms: int = 10000) -> Optional[bytes]:
    img = page.locator("div.ex_area img").first
    try:
        img.wait_for(state="visible", timeout=timeout_ms)
    except Exception:  # noqa: BLE001
        return None
    try:
        return img.screenshot(type="png")
    except Exception:  # noqa: BLE001
        return None


def ensure_page(context: BrowserContext, cfg: MacroConfig) -> Page:
    page = context.new_page()
    page.goto(cfg.initial_url, wait_until="domcontentloaded")
    return page


def run_macro(cfg: MacroConfig) -> None:
    cracker = CaptchaCrackerAdapter()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=cfg.headless)
        context = browser.new_context()
        page = ensure_page(context, cfg)

        print("[INFO] 로그인 완료 상태를 확인한 뒤 엔터를 누르세요.")
        input()

        last_reload = time.time()

        while True:
            try:
                js_wait_for_knockout(page)

                ok = js_change_month_and_select_day(page, cfg.target_month, cfg.target_day)
                if not ok:
                    print("[WARN] 날짜 탐색 실패 -> reload")
                    page.reload(wait_until="domcontentloaded")
                    continue

                time.sleep(0.2)

                if cfg.site_no > 0:
                    ok = js_select_site(page, cfg.area_name, cfg.site_no)
                else:
                    ok = js_scan_and_select_available(page)

                if not ok:
                    print("[WARN] 사이트 선택 실패 -> reload")
                    page.reload(wait_until="domcontentloaded")
                    continue

                time.sleep(0.2)

                if not js_click_reservation(page):
                    print("[WARN] 예약 클릭 실패 -> reload")
                    page.reload(wait_until="domcontentloaded")
                    continue

                captcha_bytes = wait_and_capture_captcha(page)
                if not captcha_bytes:
                    print("[WARN] captcha 이미지 대기 실패 -> reload")
                    page.reload(wait_until="domcontentloaded")
                    continue

                send_telegram(cfg.telegram_bot_token, cfg.telegram_chat_id, "Check Gangdong reservation.")
                captcha_text = cracker.solve_bytes(captcha_bytes)
                print(f"[INFO] captcha text: {captcha_text}")

                if not captcha_text:
                    print("[WARN] captcha OCR empty -> reload")
                    page.reload(wait_until="domcontentloaded")
                    continue

                ok = js_fill_captcha_and_confirm(page, captcha_text)
                if ok:
                    print("[INFO] captcha 입력 및 confirm 완료")
                    time.sleep(3)
                else:
                    print("[WARN] captcha confirm 실패 -> reload")
                    page.reload(wait_until="domcontentloaded")

                if time.time() - last_reload > cfg.reload_interval_s:
                    page.reload(wait_until="domcontentloaded")
                    last_reload = time.time()

            except KeyboardInterrupt:
                print("[INFO] 사용자 중단")
                break
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] 예외 발생: {exc} -> reload")
                try:
                    page.reload(wait_until="domcontentloaded")
                except Exception:  # noqa: BLE001
                    page = ensure_page(context, cfg)

        context.close()
        browser.close()


def parse_args() -> MacroConfig:
    parser = argparse.ArgumentParser(description="Gangdong reservation macro (Python)")
    parser.add_argument("--target-month", type=int, required=True, help="목표 월 (예: 4)")
    parser.add_argument("--target-day", type=int, required=True, help="목표 일 (예: 19)")
    parser.add_argument("--area-name", type=int, default=2, help="시설코드 0:가족 1:오토 2:매화")
    parser.add_argument("--site-no", type=int, default=6, help=">0 고정 사이트, <=0 빈자리 탐색")
    parser.add_argument("--reload-interval", type=int, default=600, help="주기적 새로고침(초)")
    parser.add_argument("--headless", action="store_true", help="헤드리스 실행")
    parser.add_argument("--telegram-bot-token", default=os.getenv("TELEGRAM_BOT_TOKEN"))
    parser.add_argument("--telegram-chat-id", default=os.getenv("TELEGRAM_CHAT_ID"))
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
    )


if __name__ == "__main__":
    run_macro(parse_args())
