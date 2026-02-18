import json
import os
import re
import sys
import time
import signal
from datetime import datetime, date
from typing import Optional, Dict, Any, List

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

START_URL = "https://www.banki.ru/services/responses/bank/gazprombank/?is_countable=on"

# 🔧 настройки
SAVE_EVERY_ITEMS = 200
SAVE_EVERY_MS = 30_000
CHECKPOINT_FILE = "links.json"

CLICK_MORE_TRIES = 5000
WAIT_AFTER_CLICK_MS = 2500
SCROLL_AFTER_CLICK_MS = 1500

# 🔧 фильтр по датам
DATE_FROM = date(2025, 1, 1)
DATE_TO   = date(2026, 2, 8)

EARLY_STOP_ON_OLD = True
OLD_BATCH_STREAK_TO_STOP = 3


def delay_ms(ms: int) -> None:
    time.sleep(ms / 1000.0)


def parse_date_iso(date_raw: Optional[str]) -> Optional[str]:
    """
    "dd.mm.yyyy" -> "yyyy-mm-dd"
    """
    if not date_raw:
        return None
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", date_raw)
    if not m:
        return None
    dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
    return f"{yyyy}-{mm}-{dd}"


def iso_to_date(iso: str) -> date:
    return datetime.strptime(iso, "%Y-%m-%d").date()


def in_range(iso: Optional[str]) -> bool:
    # если даты нет — считаем, что ок
    if not iso:
        return True
    d = iso_to_date(iso)
    return (d >= DATE_FROM) and (d <= DATE_TO)


def read_checkpoint(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception:
        print("⚠️ Чекпоинт повреждён — начнём заново")
        return []


def write_checkpoint(path: str, items: List[Dict[str, Any]]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def main() -> None:
    print("🚀 parser_links.py — сбор ссылок c фильтром по датам на листинге")

    # 1) Загружаем чекпоинт
    items: List[Dict[str, Any]] = read_checkpoint(CHECKPOINT_FILE)
    if items:
        print(f"🔄 Найдено в чекпоинте: {len(items)} записей")
    ids = set(x.get("id") for x in items if isinstance(x, dict))

    # автосейв
    last_saved_at = time.time()
    added_since_last_save = 0

    def save_now(reason: str = "manual") -> None:
        nonlocal last_saved_at, added_since_last_save
        try:
            write_checkpoint(CHECKPOINT_FILE, items)
            last_saved_at = time.time()
            added_since_last_save = 0
            print(f"💾 Сохранено ({reason}): всего {len(items)}")
        except Exception as e:
            print("⚠️ Ошибка при сохранении:", str(e))

    # страховочные обработчики
    def emergency_save(msg: str, exit_code: int = 1) -> None:
        print(f"\n🛑 {msg} — экстренное сохранение {len(items)} элементов")
        save_now("emergency")
        raise SystemExit(exit_code)

    def handle_sigint(signum, frame):
        emergency_save("SIGINT", 1)

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/127.0.0.0 Safari/537.36"
                ),
                viewport=None,
            )
            page = context.new_page()

            print("🌐 Открываю:", START_URL)
            page.goto(START_URL, wait_until="domcontentloaded", timeout=0)

            try:
                page.wait_for_selector("[data-test='responses__response']", timeout=60_000)
            except PlaywrightTimeoutError:
                print("❌ Не дождался карточек responses__response — стоп.")
                save_now("final_timeout")
                browser.close()
                return

            print("✅ Стартовая партия карточек прогружена")

            tries = 0
            old_batch_streak = 0

            while tries < CLICK_MORE_TRIES:
                tries += 1

                # Забираем батч с DOM (похоже на page.$$eval)
                batch = page.eval_on_selector_all(
                    "[data-test='responses__response']",
                    """
                    (nodes) => nodes.map((n) => {
                      const a = n.querySelector("h3 a, [data-test='link-text']");
                      const href = a?.getAttribute("href") || "";
                      const link = href ? (href.startsWith("http") ? href : `https://www.banki.ru${href}`) : null;
                      const idMatch = link?.match(/response\\/(\\d+)/);
                      const id = idMatch ? Number(idMatch[1]) : null;
                      const title =
                        n.querySelector("h3")?.textContent?.trim() ||
                        n.querySelector("[data-test='link-text']")?.textContent?.trim() ||
                        null;
                      const dateRaw = n.querySelector(".Responsesstyled__StyledItemSmallText-sc-150koqm-4")
                        ?.textContent?.trim() || null;
                      return { id, link, title, dateRaw };
                    })
                    """
                )

                added = 0
                skipped = 0
                dups = 0
                batch_all_old = True

                for b in batch or []:
                    if not b or not b.get("id") or not b.get("link"):
                        continue

                    date_iso = parse_date_iso(b.get("dateRaw"))
                    if date_iso:
                        d = iso_to_date(date_iso)
                        if d >= DATE_FROM:
                            batch_all_old = False

                    if not in_range(date_iso):
                        skipped += 1
                        continue

                    bid = b["id"]
                    if bid in ids:
                        dups += 1
                        continue

                    ids.add(bid)
                    items.append({
                        "id": bid,
                        "link": b["link"],
                        "title": b.get("title") or None,
                        "date": date_iso
                    })
                    added += 1
                    added_since_last_save += 1

                print(
                    f"📦 Батч#{tries}: карточек={len(batch) if batch else 0} | "
                    f"+{added} новых | 🔁 дубликатов {dups} | "
                    f"⏭️ вне диапазона {skipped} | всего={len(items)}"
                )

                # ранняя остановка
                if EARLY_STOP_ON_OLD:
                    if (batch and len(batch) > 0 and batch_all_old and added == 0):
                        old_batch_streak += 1
                        print(f"⏳ Пошли только старые даты (стрик={old_batch_streak}/{OLD_BATCH_STREAK_TO_STOP})")
                    else:
                        old_batch_streak = 0

                    if old_batch_streak >= OLD_BATCH_STREAK_TO_STOP:
                        print("🛑 Дальше только старые даты — стоп.")
                        break

                # автосейвы
                if added_since_last_save >= SAVE_EVERY_ITEMS:
                    save_now(f"items>={SAVE_EVERY_ITEMS}")

                if (time.time() - last_saved_at) * 1000 >= SAVE_EVERY_MS:
                    save_now(f"timer>={SAVE_EVERY_MS}ms")

                # клик "Показать ещё"
                more_btn = page.query_selector("[data-test='responses__more-btn']")
                if not more_btn:
                    print("❌ Кнопка 'Показать ещё' не найдена — стоп.")
                    break

                print(f"👉 [{tries}] Кликаю «Показать ещё»…")
                more_btn.click()
                delay_ms(WAIT_AFTER_CLICK_MS)
                page.evaluate("() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'instant' })")
                delay_ms(SCROLL_AFTER_CLICK_MS)

            save_now("final")
            print("🎉 Готово. Всего собрано:", len(items))

            in_range_count = sum(1 for x in items if in_range(x.get("date")))
            print(f"📊 Итог: в диапазоне={in_range_count}, всего={len(items)}")

            browser.close()

    except SystemExit:
        raise
    except Exception as e:
        print("💥 Ошибка:", repr(e))
        emergency_save("exception", 1)


if __name__ == "__main__":
    main()