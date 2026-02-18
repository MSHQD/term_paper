import json
import os
import re
import time
import signal
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


START_URL = "https://www.banki.ru/services/responses/bank/gazprombank/?is_countable=on"

# === Настройки ===
DATE_FROM = date(2025, 1, 1)
DATE_TO   = date(2026, 2, 8)

MAX_REVIEWS = 5000            # общий лимит (карточки/ссылки)
CLICK_MORE_TRIES = 1000       # максимум кликов "Показать ещё"
SAVE_EVERY = 50               # автосейв каждые N отзывов
PAGE_TIMEOUT_MS = 60_000

CHECKPOINT_FILE = "checkpoint.json"
OUTPUT_FILE = "reviews_full.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/127.0.0.0 Safari/537.36")


def delay_ms(ms: int) -> None:
    time.sleep(ms / 1000.0)


def parse_date_iso_ddmmyyyy(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", s)
    if not m:
        return None
    dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
    return f"{yyyy}-{mm}-{dd}"


def iso_to_date(iso: str) -> date:
    return datetime.strptime(iso, "%Y-%m-%d").date()


def in_range(iso: Optional[str]) -> bool:
    # как в твоём JS: если даты нет — не фильтруем (считаем ОК)
    if not iso:
        return True
    d = iso_to_date(iso)
    return DATE_FROM <= d <= DATE_TO


def read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json_atomic(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def main() -> None:
    print("🚀 Запуск Playwright...")

    # Загружаем чекпоинт
    checkpoint = read_json(CHECKPOINT_FILE, {"done": []})
    if not isinstance(checkpoint, dict):
        checkpoint = {"done": []}

    results: List[Dict[str, Any]] = checkpoint.get("done") or []
    if not isinstance(results, list):
        results = []

    done_ids = set(x.get("id") for x in results if isinstance(x, dict) and x.get("id") is not None)

    processed_total = len(results)
    added_total = len(results)

    def save_checkpoint(reason: str) -> None:
        write_json_atomic(CHECKPOINT_FILE, {"done": results})
        print(f"💾 Сохранено ({reason}): {len(results)} отзывов")

    def save_final() -> None:
        write_json_atomic(CHECKPOINT_FILE, {"done": results})
        write_json_atomic(OUTPUT_FILE, results)

    def handle_sigint(signum, frame):
        print("\n🛑 SIGINT — экстренный сейв")
        save_final()
        raise SystemExit(1)

    signal.signal(signal.SIGINT, handle_sigint)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = browser.new_context(user_agent=UA, viewport=None)
        page = context.new_page()

        print("🌐 Открываю:", START_URL)
        page.goto(START_URL, wait_until="domcontentloaded", timeout=0)

        print("⏳ Жду появления отзывов...")
        page.wait_for_selector("[data-test='responses__response']", timeout=PAGE_TIMEOUT_MS)
        print("✅ Отзывы найдены!")

        if results:
            print(f"🔄 Загружен чекпоинт, уже собрано: {len(results)}")

        # Жмём "Показать ещё"
        tries = 0
        while True:
            count = page.eval_on_selector_all(
                "[data-test='responses__response']",
                "els => els.length"
            )
            print(f"📊 Сейчас карточек на странице: {count}")

            if count >= MAX_REVIEWS:
                break
            if tries >= CLICK_MORE_TRIES:
                print("⚠️ Достигнут лимит нажатий 'Показать ещё'.")
                break

            more_btn = page.query_selector("[data-test='responses__more-btn']")
            if not more_btn:
                print("ℹ️ Кнопка 'Показать ещё' не найдена.")
                break

            tries += 1
            print(f"👉 [{tries}] Кликаю 'Показать ещё'...")
            more_btn.click()
            delay_ms(2500)
            page.evaluate("() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'instant' })")
            delay_ms(1500)

        # Список ссылок с листинга
        print("📦 Собираю список ссылок с листинга...")
        listing: List[Dict[str, Any]] = page.eval_on_selector_all(
            "[data-test='responses__response']",
            """
            (nodes) => nodes.map((n) => {
              const a = n.querySelector("h3 a, [data-test='link-text']");
              const href = a?.getAttribute("href") || "";
              const link = href.startsWith("http") ? href : href ? `https://www.banki.ru${href}` : null;

              const idMatch = link?.match(/response\\/(\\d+)\\/?/);
              const id = idMatch ? Number(idMatch[1]) : null;

              const title =
                n.querySelector("h3")?.textContent?.trim() ||
                n.querySelector("[data-test='link-text']")?.textContent?.trim() ||
                null;

              return { id, link, title, date: null, text: null, rating: null };
            })
            """
        )

        reviews = [r for r in (listing or []) if r.get("link") and r.get("id")]
        reviews = reviews[:MAX_REVIEWS]
        print(f"🔗 Отобрано ссылок для глубокого парсинга: {len(reviews)}")

        done = 0
        for r in reviews:
            rid = r.get("id")
            link = r.get("link")
            if not rid or not link:
                continue
            if rid in done_ids:
                continue  # уже в чекпоинте

            done += 1
            processed_total += 1
            print(f"📖 [{done}/{len(reviews)}] Открываю {link}")

            sub = context.new_page()
            try:
                sub.goto(link, wait_until="domcontentloaded", timeout=0)
                try:
                    sub.wait_for_selector("h1", timeout=10_000)
                except PlaywrightTimeoutError:
                    pass

                got = {"title": None, "text": None, "rating": None, "dateIso": None}

                # JSON-LD (берём первый script, как в твоём JS)
                json_ld = None
                try:
                    json_ld = sub.eval_on_selector('script[type="application/ld+json"]', "el => el.textContent")
                except Exception:
                    json_ld = None

                if json_ld:
                    try:
                        data = json.loads(json_ld)

                        review_body_html = (
                            data.get("reviewBody")
                            or (data.get("author", {}) if isinstance(data.get("author"), dict) else {}).get("reviewBody")
                            or (data.get("author", {}) if isinstance(data.get("author"), dict) else {}).get("description")
                            or data.get("description")
                            or None
                        )

                        full_text = sub.evaluate(
                            """(html) => {
                              if (!html) return null;
                              const d = document.createElement("div");
                              d.innerHTML = html;
                              return d.innerText.replace(/\\s+/g, " ").trim();
                            }""",
                            review_body_html
                        )

                        rating = None
                        rr = data.get("reviewRating")
                        if rr is not None:
                            if isinstance(rr, dict):
                                rating = rr.get("ratingValue") or rr.get("value") or rr
                            else:
                                rating = rr

                        title = data.get("name") or None

                        got["text"] = full_text or None
                        got["rating"] = str(rating) if rating is not None else None
                        got["title"] = title or None
                    except Exception:
                        pass

                # Фолбэки
                if not got["text"]:
                    try:
                        got["text"] = sub.evaluate(
                            """() => {
                              const sels = [
                                "[data-test='response-body']",
                                ".responses__text",
                                "article",
                                ".page-container__body [itemprop='reviewBody']",
                              ];
                              for (const sel of sels) {
                                const el = document.querySelector(sel);
                                if (el) return el.innerText.replace(/\\s+/g, " ").trim();
                              }
                              return null;
                            }"""
                        )
                    except Exception:
                        got["text"] = None

                if not got["title"]:
                    try:
                        got["title"] = sub.eval_on_selector("h1", "h => h.textContent.trim()")
                    except Exception:
                        got["title"] = r.get("title") or None

                if not got["rating"]:
                    try:
                        got["rating"] = sub.evaluate(
                            """() => {
                              const gradeDigit = document.querySelector("[data-test='grade']")?.textContent?.trim();
                              if (gradeDigit && /^\\d$/.test(gradeDigit)) return gradeDigit;

                              const divWithValue = Array.from(document.querySelectorAll("div[value]"))
                                .find((d) => /^\\d$/.test(d.getAttribute("value") || ""));
                              return divWithValue?.getAttribute("value") || null;
                            }"""
                        )
                    except Exception:
                        got["rating"] = None

                # Дата
                date_iso = None
                date_raw = None
                try:
                    date_raw = sub.eval_on_selector("time", "t => t.textContent.trim()")
                except Exception:
                    date_raw = None

                if date_raw:
                    date_iso = parse_date_iso_ddmmyyyy(date_raw)

                if not date_iso and got["text"]:
                    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", got["text"] or "")
                    if m:
                        date_iso = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

                r["title"] = got["title"] or r.get("title") or None
                r["text"] = got["text"] or None
                r["rating"] = got["rating"] or None
                r["date"] = date_iso

                # Фильтр по датам
                if date_iso and not in_range(date_iso):
                    print(f"⏭️ Вне диапазона: {date_iso}")
                    continue

                results.append({
                    "id": rid,
                    "link": link,
                    "date": date_iso or None,
                    "title": r["title"],
                    "text": r["text"],
                    "rating": r["rating"],
                })
                done_ids.add(rid)
                added_total += 1

                title_preview = (r["title"] or "")[:60]
                print(f'   ✅ ok | id={rid} | rating={r["rating"] or "-"} | date={date_iso or "-"} | title="{title_preview}"')

                if len(results) % SAVE_EVERY == 0:
                    save_checkpoint(f"autosave_{len(results)}")

            except Exception as e:
                print(f"   ⚠️ Ошибка на {link}: {e}")
            finally:
                try:
                    sub.close()
                except Exception:
                    pass
                delay_ms(800)

        # финальные сейвы
        save_final()

        print(f"🎉 Готово! Пройдено всего: {processed_total}, собрано по диапазону: {added_total}")
        browser.close()


if __name__ == "__main__":
    main()