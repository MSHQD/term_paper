import json
import os
import re
import time
import signal
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


LINKS_FILE = "links.json"
OUTPUT_FILE = "reviews.json"
CHECKPOINT_FILE = "checkpoint_texts.json"
SAVE_EVERY = 10
START_INDEX = 0

DATE_FROM = date(2025, 1, 1)
DATE_TO   = date(2026, 2, 8)


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
    # как в JS: если даты нет — пропускаем фильтр (считаем ок)
    if not iso:
        return True
    d = iso_to_date(iso)
    return (d >= DATE_FROM) and (d <= DATE_TO)


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


def strip_html(s: str) -> str:
    # убираем теги + нормализуем пробелы
    s = re.sub(r"<[^>]*>", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def main() -> None:
    print("🚀 parser_texts.py — глубокий парсинг отзывов")

    links = read_json(LINKS_FILE, [])
    if not isinstance(links, list) or not links:
        print("⚠️ Файл links.json пустой или не список")
        return

    checkpoint = read_json(CHECKPOINT_FILE, {"doneIds": [], "reviews": []})
    if not isinstance(checkpoint, dict):
        checkpoint = {"doneIds": [], "reviews": []}

    done_ids = set(checkpoint.get("doneIds") or [])
    results: List[Dict[str, Any]] = checkpoint.get("reviews") or []
    if results:
        print(f"🔄 Чекпоинт: уже собрано {len(results)}")

    # Экстренное сохранение
    def save_all(reason: str) -> None:
        write_json_atomic(CHECKPOINT_FILE, {"doneIds": sorted(list(done_ids)), "reviews": results})
        write_json_atomic(OUTPUT_FILE, results)
        print(f"💾 Сохранено ({reason}): reviews={len(results)} doneIds={len(done_ids)}")

    def handle_sigint(signum, frame):
        print("\n🛑 SIGINT — экстренное сохранение")
        save_all("emergency_sigint")
        raise SystemExit(1)

    signal.signal(signal.SIGINT, handle_sigint)

    processed_total = 0
    skipped_by_date = 0

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

        for i in range(START_INDEX, len(links)):
            r = links[i]
            if not isinstance(r, dict):
                continue

            rid = r.get("id")
            link = r.get("link")
            if not rid or not link:
                continue
            if rid in done_ids:
                continue

            processed_total = i + 1
            print(f"📖 {processed_total}/{len(links)} — id={rid}")

            page = context.new_page()

            try:
                page.goto(link, wait_until="domcontentloaded", timeout=0)
                delay_ms(2500)
                try:
                    page.wait_for_selector("h1, [data-test='response-body']", timeout=15_000)
                except PlaywrightTimeoutError:
                    pass

                got: Dict[str, Optional[str]] = {"title": None, "text": None, "rating": None, "date": None}

                # === JSON-LD ===
                json_ld_text = None
                try:
                    json_ld_text = page.eval_on_selector(
                        'script[type="application/ld+json"]',
                        "el => el.textContent"
                    )
                except Exception:
                    json_ld_text = None

                if json_ld_text:
                    try:
                        clean = re.sub(r"[\u0000-\u001F]+", " ", json_ld_text)
                        data = json.loads(clean)

                        review_body_html = (
                            data.get("reviewBody")
                            or (data.get("author", {}) if isinstance(data.get("author"), dict) else {}).get("reviewBody")
                            or (data.get("author", {}) if isinstance(data.get("author"), dict) else {}).get("description")
                            or data.get("description")
                            or None
                        )

                        full_text = None
                        if review_body_html:
                            # декодируем html-сущности через DOM
                            decoded = page.evaluate(
                                """(raw) => {
                                  const t = document.createElement("textarea");
                                  t.innerHTML = raw;
                                  return t.value;
                                }""",
                                review_body_html
                            )
                            if isinstance(decoded, str):
                                full_text = strip_html(decoded)

                        rating = None
                        rr = data.get("reviewRating")
                        if rr is not None:
                            if isinstance(rr, dict):
                                rating = rr.get("ratingValue") or rr.get("value") or rr
                            else:
                                rating = rr

                        got["text"] = full_text or None
                        got["rating"] = str(rating) if rating is not None else None
                        got["title"] = data.get("name") or None

                    except Exception as e:
                        print(f"⚠️ JSON-LD parse error on id={rid}: {e}")

                # === Фолбэки ===
                if not got["text"]:
                    try:
                        got["text"] = page.evaluate(
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
                        got["title"] = page.eval_on_selector("h1", "h => h.textContent.trim()")
                    except Exception:
                        got["title"] = r.get("title") or None

                if not got["rating"]:
                    try:
                        got["rating"] = page.evaluate(
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

                # === Город ===
                city = None
                try:
                    city = page.eval_on_selector(".l3a372298", "el => el.textContent.trim()")
                    if isinstance(city, str) and city:
                        city = re.sub(r"\s*\(.*?\)\s*$", "", city).strip()
                except Exception:
                    city = None

                # === Дата ===
                date_iso = None
                date_raw = None

                try:
                    date_raw = page.eval_on_selector("time", "t => t.textContent.trim()")
                except Exception:
                    date_raw = None

                if not date_raw:
                    try:
                        date_raw = page.eval_on_selector(".l51115aff .l10fac986", "el => el.textContent.trim()")
                    except Exception:
                        date_raw = None

                if date_raw:
                    date_iso = parse_date_iso_ddmmyyyy(date_raw)

                if not date_iso and got.get("text"):
                    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", got["text"] or "")
                    if m:
                        date_iso = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

                # фильтр по датам
                if date_iso and not in_range(date_iso):
                    print(f"⏭️ Пропущен вне диапазона: {date_iso}")
                    skipped_by_date += 1
                    continue

                results.append({
                    "id": rid,
                    "link": link,
                    "date": date_iso,
                    "title": got.get("title") or r.get("title"),
                    "text": got.get("text"),
                    "rating": got.get("rating"),
                    "city": city,
                })
                done_ids.add(rid)

                title_preview = (got.get("title") or "")[:60]
                print(f'   ✅ ok | id={rid} | date={date_iso or "-"} | rating={got.get("rating") or "-"} | title="{title_preview}"')

                if (len(results) % SAVE_EVERY) == 0:
                    save_all(f"autosave_{len(results)}")

            except Exception as e:
                print(f"⚠️ Ошибка на {link}: {e}")
            finally:
                try:
                    page.close()
                except Exception as e:
                    print(f"⚠️ Ошибка при закрытии вкладки (id={rid}): {e}")
                delay_ms(1000)

        save_all("final")

        print("\n🎉 Готово!")
        print(f"📊 Всего обработано (индекс последнего): {processed_total}")
        print(f"✅ Сохранено в диапазоне: {len(results)}")
        print(f"⏭️ Пропущено по датам: {skipped_by_date}")

        browser.close()


if __name__ == "__main__":
    main()