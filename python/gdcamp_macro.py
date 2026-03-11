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
    """Wrapper to support multiple CaptchaCracker API shapes."""

    def __init__(self) -> None:
        lib = None
        errors = []
        for mod in ("CaptchaCracker", "captchacracker"):
            try:
                lib = __import__(mod)
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{mod}: {exc}")
        if lib is None:
            raise RuntimeError(
                "CaptchaCracker import failed. Install with: pip install CaptchaCracker "
                f"(errors: {' | '.join(errors)})"
            )
        self._lib = lib

    def _signature_arg_candidates(self, fn: object, image_bytes: bytes, image_path: str):
        try:
            sig = inspect.signature(fn)
            params = [p for p in sig.parameters.values() if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        except Exception:  # noqa: BLE001
            return []

        if not params:
            return []

        candidates = []
        first = params[0].name.lower()
        if "path" in first or "file" in first:
            candidates.append({params[0].name: image_path})
        if "byte" in first or "image" in first or "img" in first or "data" in first:
            candidates.append({params[0].name: image_bytes})
        return candidates

    def _try_apply_model_variants(self, owner: object, image_bytes: bytes) -> Optional[str]:
        create_model = getattr(owner, "CreateModel", None)
        apply_model = getattr(owner, "ApplyModel", None)
        if not callable(apply_model):
            return None

        model_candidates = [None]
        if callable(create_model):
            for model_arg in (None, "", "default", "captcha", "core"):
                try:
                    model = create_model() if model_arg is None else create_model(model_arg)
                    model_candidates.append(model)
                except Exception:  # noqa: BLE001
                    continue

        import tempfile as _tempfile
        with _tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
            tmp.write(image_bytes)
            tmp.flush()
            payloads = [image_bytes, memoryview(image_bytes), tmp.name]

            for model in model_candidates:
                for payload in payloads:
                    # positional attempts
                    positional_attempts = []
                    if model is None:
                        positional_attempts.append((payload,))
                    else:
                        positional_attempts.extend([(model, payload), (payload, model)])

                    for args in positional_attempts:
                        try:
                            result = apply_model(*args)
                        except Exception:  # noqa: BLE001
                            continue
                        text = self._normalize(result)
                        if text:
                            return text

                    # keyword attempts based on signature hints
                    for kwargs in self._signature_arg_candidates(apply_model, image_bytes, tmp.name):
                        try:
                            if model is not None:
                                kwargs = {**kwargs, "model": model}
                            result = apply_model(**kwargs)
                        except Exception:  # noqa: BLE001
                            continue
                        text = self._normalize(result)
                        if text:
                            return text

        return None

    def solve_bytes(self, image_bytes: bytes) -> str:
        lib = self._lib

        def _try_call(fn: object) -> Optional[str]:
            if not callable(fn):
                return None

            call_variants = [
                (image_bytes,),
                (memoryview(image_bytes),),
            ]

            import tempfile as _tempfile
            with _tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
                tmp.write(image_bytes)
                tmp.flush()
                call_variants.append((tmp.name,))

                for args in call_variants:
                    try:
                        result = fn(*args)
                    except TypeError:
                        # try kwargs style if signature hints parameter names
                        try:
                            sig = inspect.signature(fn)
                            params = list(sig.parameters)
                            if not params:
                                continue
                            name = params[0].lower()
                            if "path" in name or "file" in name:
                                result = fn(**{params[0]: tmp.name})
                            elif "byte" in name or "image" in name:
                                result = fn(**{params[0]: image_bytes})
                            else:
                                continue
                        except Exception:  # noqa: BLE001
                            continue
                    except Exception:  # noqa: BLE001
                        continue

                    text = self._normalize(result)
                    if text:
                        return text
            return None

        # Variant A: class-based API (e.g., CaptchaCracker().solve/predict/crack)
        for cls_name in ("CaptchaCracker", "Solver", "Cracker"):
            cls = getattr(lib, cls_name, None)
            if cls is None:
                continue
            try:
                inst = cls()
            except Exception:  # noqa: BLE001
                continue
            for method_name in ("solve", "predict", "crack", "run", "decode", "recognize"):
                text = _try_call(getattr(inst, method_name, None))
                if text:
                    return text

        # Variant B: module-level callables
        for fn_name in ("solve", "predict", "crack", "run", "decode", "recognize"):
            text = _try_call(getattr(lib, fn_name, None))
            if text:
                return text

        # Variant C: nested objects that expose solver methods
        for attr_name in dir(lib):
            if attr_name.startswith("_"):
                continue
            obj = getattr(lib, attr_name, None)
            for method_name in ("solve", "predict", "crack", "run", "decode", "recognize"):
                text = _try_call(getattr(obj, method_name, None))
                if text:
                    return text


        # Variant D: CreateModel/ApplyModel style APIs
        for owner in (lib, getattr(lib, "core", None)):
            if owner is None:
                continue
            text = self._try_apply_model_variants(owner, image_bytes)
            if text:
                return text

        # Soft fallback: do not crash macro loop on unknown API shape.
        # Return empty text so caller can retry/reload.
        public_attrs = [x for x in dir(lib) if not x.startswith('_')][:30]
        print(
            "[WARN] Unsupported CaptchaCracker API shape; available attrs sample: "
            + ", ".join(public_attrs)
        )
        return ""

    @staticmethod
    def _normalize(value: object) -> str:
        if value is None:
            return ""

        # Common structured returns
        if isinstance(value, dict):
            for key in ("text", "result", "value", "captcha", "code"):
                if key in value:
                    return CaptchaCrackerAdapter._normalize(value[key])
            return ""

        if isinstance(value, (list, tuple)):
            for item in value:
                text = CaptchaCrackerAdapter._normalize(item)
                if text:
                    return text
            return ""

        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                return ""

        text = str(value)
        # Keep only alnum because captcha target is short token
        text = re.sub(r"[^0-9A-Za-z]", "", text)
        return text.strip()


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
    """Capture captcha image bytes without using Playwright locator APIs."""
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            data_url = page.evaluate(
                """
                () => {
                  const img = document.querySelector('div.ex_area img');
                  if (!img) return null;
                  const width = img.naturalWidth || img.width;
                  const height = img.naturalHeight || img.height;
                  if (!width || !height) return null;

                  const canvas = document.createElement('canvas');
                  canvas.width = width;
                  canvas.height = height;
                  const ctx = canvas.getContext('2d');
                  if (!ctx) return null;
                  ctx.drawImage(img, 0, 0, width, height);
                  return canvas.toDataURL('image/png');
                }
                """
            )
        except Exception:  # noqa: BLE001
            data_url = None

        if data_url and isinstance(data_url, str) and data_url.startswith('data:image/png;base64,'):
            try:
                return base64.b64decode(data_url.split(',', 1)[1])
            except Exception:  # noqa: BLE001
                return None

        time.sleep(0.1)

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




def is_known_playwright_eval_runtime_error(exc: Exception) -> bool:
    msg = str(exc)
    return (
        "refs.set is not a function" in msg
        or "this._engines.set is not a function" in msg
    )

def run_macro(cfg: MacroConfig) -> None:
    cracker = CaptchaCrackerAdapter()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=cfg.headless)
        context = browser.new_context()
        install_js_runtime_guards(context)
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
                    if is_known_playwright_eval_runtime_error(exc):
                        print("[WARN] Playwright evaluate runtime 오염 감지 -> context 재생성")
                        context.close()
                        context = browser.new_context()
                        install_js_runtime_guards(context)
                        page = ensure_page(context, cfg)
                    else:
                        page.reload(wait_until="domcontentloaded")
                except Exception:  # noqa: BLE001
                    context.close()
                    context = browser.new_context()
                    install_js_runtime_guards(context)
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
