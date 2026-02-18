import json
import re
import time
import sys
from playwright.sync_api import sync_playwright


START_URL = "https://www.banki.ru/services/responses/bank/gazprombank/?is_countable=on"

MAX_REVIEWS = 1000
CLICK_MORE_TRIES = 200
PAGE_TIMEOUT = 60000  # ms


def delay(ms: int) -> None:
    time.sleep(ms / 1000.0)


def write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main() -> None:
    print("Запуск Playwright...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
            ),
            viewport=None,
        )
        page = context.new_page()

        print("Открываю:", START_URL)
        page.goto(START_URL, wait_until="domcontentloaded", timeout=0)

        print("Жду появления отзывов...")
        page.wait_for_selector("[data-test='responses__response']", timeout=PAGE_TIMEOUT)
        print("Отзывы найдены!")

        tries = 0
        while True:
            count = page.eval_on_selector_all(
                "[data-test='responses__response']",
                "els => els.length"
            )
            print(f"Сейчас карточек на странице: {count}")

            if count >= MAX_REVIEWS:
                break
            if tries >= CLICK_MORE_TRIES:
                print("Достигнут лимит нажатий 'Показать ещё'. Едем дальше.")
                break

            more_btn = page.query_selector("[data-test='responses__more-btn']")
            if not more_btn:
                print("Кнопка 'Показать ещё' не найдена.")
                break

            tries += 1
            print(f"👉 [{tries}] Кликаю 'Показать ещё'...")
            more_btn.click()
            delay(2200)
            page.evaluate("() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'instant' })")
            delay(1200)

        print("Собираю список ссылок с листинга...")
        list_items = page.eval_on_selector_all(
            "[data-test='responses__response']",
            """
            (nodes) => nodes.slice(0, 200).map((n) => {
              const a = n.querySelector("h3 a, [data-test='link-text']");
              const href = a?.getAttribute("href") || "";
              const link = href.startsWith("http")
                ? href
                : href
                ? `https://www.banki.ru${href}`
                : null;

              const idMatch = link?.match(/response\\/(\\d+)\\/?/);
              const id = idMatch ? Number(idMatch[1]) : null;

              const title =
                n.querySelector("h3")?.textContent?.trim() ||
                n.querySelector("[data-test='link-text']")?.textContent?.trim() ||
                null;

              const dateRaw =
                n.querySelector(".Responsesstyled__StyledItemSmallText-sc-150koqm-4")?.textContent?.trim() ||
                n.textContent.match(/\\d{2}\\.\\d{2}\\.\\d{4}/)?.[0] ||
                null;

              // yyyy-mm-dd
              let date = null;
              if (dateRaw) {
                const m = dateRaw.match(/(\\d{2})\\.(\\d{2})\\.(\\d{4})/);
                if (m) date = `${m[3]}-${m[2]}-${m[1]}`;
              }

              const gradeAttr = n.getAttribute("data-test-grade");
              const rating = gradeAttr ? String(gradeAttr) : null;

              const teaser =
                n.querySelector(".Responsesstyled__StyledItemText-sc-150koqm-3 a")
                  ?.textContent?.trim() || null;

              return { id, link, date, title, text: null, rating, teaser };
            })
            """
        )

        reviews = [r for r in (list_items or []) if r.get("link") and r.get("id")][:MAX_REVIEWS]
        print(f"🔗 Отобрано ссылок для глубокого парсинга: {len(reviews)}")

        done = 0
        for r in reviews:
            done += 1
            print(f"📖 [{done}/{len(reviews)}] Открываю {r['link']}")

            sub = context.new_page()
            try:
                sub.goto(r["link"], wait_until="domcontentloaded", timeout=0)

                json_ld = None
                try:
                    json_ld = sub.eval_on_selector('script[type="application/ld+json"]', "el => el.textContent")
                except Exception:
                    json_ld = None

                got = {"title": None, "text": None, "rating": None, "dateIso": None}

                if json_ld:
                    try:
                        data = json.loads(json_ld)

                        author = data.get("author")
                        if not isinstance(author, dict):
                            author = None

                        review_body_html = (
                            data.get("reviewBody")
                            or (author.get("reviewBody") if author else None)
                            or (author.get("description") if author else None)
                            or data.get("description")
                            or None
                        )

                        full_text = sub.evaluate(
                            """(html) => {
                              if (!html) return null;
                              const d = document.createElement("div");
                              d.innerHTML = html;
                              return d.innerText.trim();
                            }""",
                            review_body_html
                        )

                        rr = data.get("reviewRating")
                        rating = None
                        if rr is not None:
                            if isinstance(rr, dict):
                                rating = rr.get("ratingValue") or rr.get("value") or rr
                            else:
                                rating = rr

                        title = data.get("name") or None
                        if not title:
                            try:
                                title = sub.eval_on_selector("h1", "h => h.textContent.trim()")
                            except Exception:
                                title = None

                        got["text"] = full_text or None
                        got["rating"] = str(rating) if rating is not None else (r.get("rating") or None)
                        got["title"] = title or (r.get("title") or None)
                    except Exception:
                        pass  # падаем в фолбэки

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
                                if (el) return el.innerText.trim();
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
                              const divWithValue = Array.from(document.querySelectorAll("div[value]")).find((d) =>
                                /^\\d$/.test(d.getAttribute("value") || "")
                              );
                              return divWithValue?.getAttribute("value") || null;
                            }"""
                        )
                    except Exception:
                        got["rating"] = None

                date_raw = None
                try:
                    date_raw = sub.eval_on_selector("time", "t => t.textContent.trim()")
                except Exception:
                    date_raw = None

                if not date_raw:
                    try:
                        date_raw = sub.eval_on_selector(".l51115aff .l10fac986", "el => el.textContent.trim()")
                    except Exception:
                        date_raw = None

                date_iso = r.get("date") or None
                if date_raw:
                    m = re.search(r"(\\d{2})\\.(\\d{2})\\.(\\d{4})", date_raw)
                    if m:
                        date_iso = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

                r["title"] = got["title"] or r.get("title") or None
                r["text"] = got["text"] or r.get("teaser") or None
                r["rating"] = got["rating"] or r.get("rating") or None
                r["date"] = date_iso

                print(
                    f'   ok | id={r["id"]} | rating={r["rating"] or "-"} | date={r["date"] or "-"} | '
                    f'title="{(r["title"] or "")[:60]}"'
                )

            except Exception as e:
                print(f"    Ошибка на {r['link']}: {e}")
            finally:
                try:
                    sub.close()
                except Exception:
                    pass
                delay(800)

        out = [
            {
                "id": r.get("id"),
                "link": r.get("link"),
                "date": r.get("date") or None,
                "title": r.get("title") or None,
                "text": r.get("text") or None,
                "rating": r.get("rating") or None,
            }
            for r in reviews
        ]

        print(f"\n Итог: собрано {len(out)} отзывов")
        write_json("reviews.json", out)
        print("Сохранено в reviews.json")

        browser.close()
        print("🎉 Готово! 🎉")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("💥💥💥 Критическая ошибка:", e)
        sys.exit(1)