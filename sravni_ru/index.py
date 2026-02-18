import json
import re
from typing import Optional, Dict, Any, List
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime, date


# Настройки для Chrome
chrome_options = webdriver.ChromeOptions()
# Можно раскомментировать для headless режима
# chrome_options.add_argument("--headless")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--window-size=1920,1080")

# Максимальная блокировка редиректов
chrome_options.add_argument("--disable-web-security")
chrome_options.add_argument("--disable-features=VizDisplayCompositor")

# Блокировка HTTP редиректов и переадресаций
chrome_options.add_argument("--disable-background-networking")
chrome_options.add_argument("--disable-background-timer-throttling")
chrome_options.add_argument("--disable-renderer-backgrounding")
chrome_options.add_argument("--disable-backgrounding-occluded-windows")
chrome_options.add_argument("--disable-client-side-phishing-detection")
chrome_options.add_argument("--disable-sync")

# Блокировка автоматических навигационных переходов
chrome_options.add_argument("--disable-background-mode")
chrome_options.add_argument("--disable-default-apps")
chrome_options.add_argument("--disable-extensions")
chrome_options.add_argument("--disable-plugins")
chrome_options.add_argument("--disable-popup-blocking")

# Сетевые ограничения для блокировки редиректов
chrome_options.add_argument("--disable-domain-reliability")
chrome_options.add_argument("--disable-component-update")
chrome_options.add_argument("--disable-background-downloads")
chrome_options.add_argument("--disable-add-to-shelf")
chrome_options.add_argument("--disable-translate")

# Безопасность и приватность (помогает блокировать редиректы)
chrome_options.add_argument("--disable-features=TranslateUI")
chrome_options.add_argument("--disable-ipc-flooding-protection")
chrome_options.add_argument("--disable-hang-monitor")
chrome_options.add_argument("--disable-prompt-on-repost")
chrome_options.add_argument("--disable-site-isolation-trials")

# Блокировка автоматических действий браузера
chrome_options.add_argument("--no-first-run")
chrome_options.add_argument("--no-default-browser-check")
chrome_options.add_argument("--disable-infobars")
chrome_options.add_argument("--disable-notifications")
chrome_options.add_argument("--disable-save-password-bubble")

# Настройки для предотвращения автоматических переходов
chrome_options.add_argument("--disable-features=AutofillServerCommunication")
chrome_options.add_argument("--disable-features=Translate")
chrome_options.add_argument("--disable-features=OptimizationHints")
chrome_options.add_argument("--disable-features=MediaRouter")
chrome_options.add_argument("--disable-features=DialMediaRouteProvider")

# Дополнительные настройки безопасности
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_argument("--disable-dev-tools")
chrome_options.add_argument("--disable-gpu-sandbox")
chrome_options.add_argument("--ignore-certificate-errors")
chrome_options.add_argument("--ignore-ssl-errors")
chrome_options.add_argument("--allow-running-insecure-content")


# Маппинг русских месяцев в числа
monthMap = {
    "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
    "мая": "05", "июня": "06", "июля": "07", "августа": "08",
    "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12",
}



DATE_FROM = date(2025, 1, 1)
DATE_TO   = date(2026, 2, 8) 


# Функция для парсинга даты
def parseDate(dateText: str) -> str:
    try:
        cleanDate = (dateText or "").strip()
        parts = cleanDate.split(" ")

        if len(parts) >= 2:
            day = parts[0].zfill(2)
            monthName = parts[1]
            year = parts[2] if len(parts) >= 3 else "2025"

            month = monthMap.get(monthName, "01")
            return f"{year}-{month}-{day}"

        return cleanDate
    except Exception as error:
        print("Ошибка парсинга даты:", dateText, str(error))
        return dateText
    

def in_date_range(date_iso: str) -> bool:
    """
    date_iso ожидается в формате YYYY-MM-DD (как возвращает parseDate)
    """
    if not date_iso:
        return False
    try:
        d = datetime.strptime(date_iso, "%Y-%m-%d").date()
        return DATE_FROM <= d <= DATE_TO
    except Exception:
        return False


# Функция для парсинга рейтинга по звездочкам
def parseRating(driver, reviewElement) -> Optional[int]:
    try:
        rateContainer = reviewElement.find_element(By.CSS_SELECTOR, '[data-qa="Rate"]')
        stars = rateContainer.find_elements(By.CSS_SELECTOR, "div._1expmgd._4czyoq")

        filledStars = 0

        for i in range(len(stars)):
            try:
                svgElement = stars[i].find_element(By.CSS_SELECTOR, 'svg[data-qa="Star"]')

                cssVars = driver.execute_script(
                    """
                    const svgElement = arguments[0];
                    const computedStyle = window.getComputedStyle(svgElement);

                    const filledStroke = computedStyle.getPropertyValue('--rate-filled-stroke');
                    const filledBgColor = computedStyle.getPropertyValue('--rate-filled-bgColor');
                    const filledColor = computedStyle.getPropertyValue('--rate-filled-color');

                    const unfilledStroke = computedStyle.getPropertyValue('--rate-unfilled-light-stroke');
                    const unfilledBgColor = computedStyle.getPropertyValue('--rate-unfilled-light-bgColor');
                    const unfilledColor = computedStyle.getPropertyValue('--rate-unfilled-light-color');

                    const actualFill = computedStyle.fill;
                    const actualStroke = computedStyle.stroke;
                    const actualColor = computedStyle.color;

                    return {
                        filled: { stroke: filledStroke, bgColor: filledBgColor, color: filledColor },
                        unfilled: { stroke: unfilledStroke, bgColor: unfilledBgColor, color: unfilledColor },
                        actual: { fill: actualFill, stroke: actualStroke, color: actualColor }
                    };
                    """,
                    svgElement,
                )

                filledColor = cssVars["filled"]["bgColor"]
                actualFill = cssVars["actual"]["fill"]

                isFilledColor = (
                    ("229, 163, 69" in (actualFill or "")) or
                    ("#e5a345" in (actualFill or "")) or
                    (actualFill == filledColor)
                )

                if isFilledColor:
                    filledStars += 1

            except Exception as e:
                print(f"   ⚠️  Не удалось обработать звездочку {i + 1}:", str(e))

        return filledStars

    except Exception as error:
        print("Не удалось определить рейтинг:", str(error))
        return None


# Функция для сохранения отзывов в JSON файл
def saveReviewsToFile(reviews: List[Dict[str, Any]], filename: str = "reviews.json") -> None:
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(reviews, f, ensure_ascii=False, indent=2)
        print(f"💾 Отзывы сохранены в файл: {filename}")
        print(f"📊 Сохранено отзывов: {len(reviews)}")
    except Exception as error:
        print("❌ Ошибка при сохранении файла:", str(error))


# Функция для парсинга одного отзыва
def parseReview(driver, reviewElement) -> Optional[Dict[str, Any]]:
    try:
        reviewId = reviewElement.get_attribute("data-id")

        linkElement = reviewElement.find_element(By.CSS_SELECTOR, 'a[class*="review-card_link"]')
        reviewLink = linkElement.get_attribute("href")
        fullLink = f"https://www.sravni.ru{reviewLink}" if (reviewLink or "").startswith("/") else reviewLink

        reviewDate = ""
        try:
            dateContainer = reviewElement.find_element(By.CSS_SELECTOR, ".h-ml-12._10cf6rv._19sgipd")
            dateElement = dateContainer.find_element(By.CSS_SELECTOR, ".h-color-D30._1aja02n._1w66l1f")
            dateText = dateElement.text
            reviewDate = parseDate(dateText)

            if not in_date_range(reviewDate):
                return None
        except Exception:
            print("Не удалось найти дату для отзыва", reviewId)

        rating = parseRating(driver, reviewElement)

        title = ""
        try:
            titleElement = reviewElement.find_element(By.CSS_SELECTOR, '[class*="review-card_title"]')
            title = titleElement.text
        except Exception:
            print("Не удалось найти заголовок для отзыва", reviewId)

        # Нажимаем кнопку "Читать" если она есть
        try:
            readButton = reviewElement.find_element(By.CSS_SELECTOR, "a._i91ye._qagut5")
            driver.execute_script("arguments[0].click();", readButton)
            time.sleep(0.3)
        except Exception:
            print('Кнопка "Читать" не найдена или уже развернут текст для отзыва', reviewId)

        reviewText = ""
        try:
            textElement = reviewElement.find_element(By.CSS_SELECTOR, '[class*="review-card_text"] span')
            reviewText = textElement.text
        except Exception:
            print("Не удалось найти текст для отзыва", reviewId)

        fullContent = f"{title}\n\n{reviewText}" if (title and reviewText) else (title or reviewText)

        return {
            "id": reviewId,
            "link": fullLink,
            "date": reviewDate,
            "rating": rating,
            "content": (fullContent or "").strip(),
        }

    except Exception as error:
        print("Ошибка при парсинге отзыва:", str(error))
        return None


# Главная функция парсера
def parseSravniGazprombank() -> None:
    driver = None

    try:
        print("🚀 Запуск парсера Sravni.ru для Газпромбанка...")

        driver = webdriver.Chrome(options=chrome_options)
        print("✅ Chrome драйвер запущен")

        url = "https://www.sravni.ru/bank/gazprombank/otzyvy/?orderby=byDate"
        print(f"🔗 Переходим на: {url}")

        driver.get(url)

        WebDriverWait(driver, 10).until(EC.title_contains("Газпромбанк"))
        print("📄 Страница загружена успешно")

        # Блокируем все редиректы на уровне JavaScript
        driver.execute_script(
            """
            const originalAssign = window.location.assign;
            const originalReplace = window.location.replace;
            const originalReload = window.location.reload;
            const originalPushState = history.pushState;
            const originalReplaceState = history.replaceState;

            window.location.assign = function(url) {
                console.log('🚫 Заблокирован location.assign на:', url);
                return false;
            };

            window.location.replace = function(url) {
                console.log('🚫 Заблокирован location.replace на:', url);
                return false;
            };

            window.location.reload = function() {
                console.log('🚫 Заблокирована перезагрузка страницы');
                return false;
            };

            history.pushState = function(state, title, url) {
                console.log('🚫 Заблокирован history.pushState на:', url);
                return false;
            };

            history.replaceState = function(state, title, url) {
                console.log('🚫 Заблокирован history.replaceState на:', url);
                return false;
            };

            document.addEventListener('submit', function(e) {
                console.log('🚫 Заблокирована отправка формы');
                e.preventDefault();
                e.stopPropagation();
                return false;
            }, true);

            document.addEventListener('click', function(e) {
                if (e.target.tagName === 'A' && e.target.href && !e.target.href.startsWith('#')) {
                    const href = e.target.href;
                    if (!href.includes('sravni.ru/bank/gazprombank/otzyv') && !href.includes('javascript:') && href !== window.location.href) {
                        console.log('🚫 Заблокирован переход по ссылке:', href);
                        e.preventDefault();
                        e.stopPropagation();
                        return false;
                    }
                }
            }, true);

            let blocked = false;
            const expectedUrl = arguments[0];

            const locationWatcher = setInterval(() => {
                if (window.location.href !== expectedUrl && !blocked) {
                    blocked = true;
                    console.log('🚫 Обнаружена попытка редиректа, блокируем...');
                    window.history.back();
                    setTimeout(() => { blocked = false; }, 1000);
                }
            }, 100);

            window.blockRedirectsActive = true;
            console.log('✅ Все редиректы заблокированы на уровне JavaScript');
            """,
            url,
        )

        print("🚫 JavaScript блокировка редиректов активирована")

        title = driver.title
        print(f"📝 Заголовок страницы: {title}")

        print("⏳ Ждем 5 секунд для визуальной проверки...")
        time.sleep(5)

        print("✅ Парсер успешно подключился к сайту!")

        print("🔍 Ищем контейнер с отзывами...")
        #####################################################################
        print("URL NOW:", driver.current_url)
        print("TITLE NOW:", driver.title)
        print("READY:", driver.execute_script("return document.readyState"))
        print("BODY LEN:", len(driver.page_source))
        driver.save_screenshot("debug.png")
        with open("debug.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print("Saved debug.png and debug.html")
        #####################################################################
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-id]")))

        #mainContainer = driver.find_element(By.CSS_SELECTOR, ".page_mainColumn__oogxd")
        #reviewsWrapper = mainContainer.find_element(By.CSS_SELECTOR, ".styles_wrapper___EM4q")
        #reviewElements = reviewsWrapper.find_elements(By.CSS_SELECTOR, "div[data-id]")
        reviewElements = driver.find_elements(By.CSS_SELECTOR, "div[data-id]")

        print(f"📋 Найдено отзывов: {len(reviewElements)}")

        targetReviews = 1000
        reviews: List[Dict[str, Any]] = []
        parsedIds = set()
        reviewQueue: List[str] = []

        print(f"🎯 Цель: спарсить {targetReviews} отзывов")

        keepScrolling = True

        def startBackgroundScroll():
            nonlocal keepScrolling, reviewQueue, reviews

            while keepScrolling:
                if len(reviewQueue) + len(reviews) >= targetReviews:
                    print(
                        f"🛑 Достаточно отзывов в очереди ({len(reviewQueue)}) + обработано ({len(reviews)}) = "
                        f"{len(reviewQueue) + len(reviews)}. Останавливаем скролл."
                    )
                    break

                if len(reviewQueue) > 0:
                    lastReviewId = reviewQueue[-1]
                    try:
                        lastElement = driver.find_element(By.CSS_SELECTOR, f'div[data-id="{lastReviewId}"]')
                        driver.execute_script(
                            "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});",
                            lastElement,
                        )
                        print(f"🎯 Скроллим к якорю - последнему отзыву в очереди: {lastReviewId}")
                    except Exception:
                        driver.execute_script("window.scrollBy(0, 300);")
                else:
                    driver.execute_script("window.scrollBy(0, 300);")

                time.sleep(2)

        def updateReviewQueue() -> int:
            nonlocal reviewQueue, reviews
            driver.execute_script("window.scrollBy(0, 1200);")
            time.sleep(1.5)
            print("🔍 Пересканируем страницу для поиска новых отзывов...")

            # 1) скроллим вниз (чтобы сайт подгрузил новые карточки)
            before = len(driver.find_elements(By.CSS_SELECTOR, "div[data-id]"))
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

            # 2) ждём, что количество карточек увеличится (или хотя бы не упадёт)
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: len(d.find_elements(By.CSS_SELECTOR, "div[data-id]")) > before
                )
            except Exception:
                pass  # если не подгрузилось — просто продолжим (логика не ломается)

            # 3) теперь заново читаем элементы
            currentReviewElements = driver.find_elements(By.CSS_SELECTOR, "div[data-id]")

            print(f"📋 Найдено {len(currentReviewElements)} отзывов на странице")

            # дальше твой код без изменений:
            reviewQueue = []

            newReviewsFound = 0
            duplicatesSkipped = 0

            for reviewElement in currentReviewElements:
                if len(reviewQueue) + len(reviews) >= targetReviews:
                    print(
                        f"🎯 Достигнута цель: в очереди ({len(reviewQueue)}) + обработано ({len(reviews)}) = "
                        f"{len(reviewQueue) + len(reviews)} отзывов"
                    )
                    break

                try:
                    reviewId = reviewElement.get_attribute("data-id")

                    if reviewId in parsedIds:
                        duplicatesSkipped += 1
                        continue

                    reviewQueue.append(reviewId)
                    newReviewsFound += 1

                except Exception as e:
                    print("⚠️ Не удалось получить ID отзыва:", str(e))

            print(f"📈 Добавлено в очередь: {newReviewsFound} новых отзывов")

            if duplicatesSkipped > 0:
                print(f"⚠️ Пропущено {duplicatesSkipped} уже обработанных отзывов")

            print(f"📊 Текущая очередь: {len(reviewQueue)} отзывов")
            print(f"📊 Уже обработано: {len(parsedIds)} отзывов")
            print(f"📊 Всего на странице: {len(currentReviewElements)} отзывов")

            if newReviewsFound > 0:
                head = reviewQueue[:3]
                print("🆔 Новые ID в очереди:", head, f"... и еще {len(reviewQueue) - 3}" if len(reviewQueue) > 3 else "")

            return newReviewsFound

        print("\n🔍 Выполняем начальное сканирование страницы...")
        initialNewReviews = updateReviewQueue()
        print(f"📋 Начальная очередь: {len(reviewQueue)} отзывов")

        if len(reviewQueue) == 0:
            print("❌ ОШИБКА: Не найдено ни одного отзыва для парсинга!")
            print("🔍 Проверьте селекторы или структуру страницы.")
            return

        def validateUniqueReviews(reviewsList: List[Dict[str, Any]]) -> bool:
            seenIds = set()
            duplicates = []

            for review in reviewsList:
                if review.get("id") in seenIds:
                    duplicates.append(review.get("id"))
                else:
                    seenIds.add(review.get("id"))

            if len(duplicates) > 0:
                print(f"⚠️ Обнаружены дубликаты в финальном списке: {', '.join(map(str, duplicates))}")
                return False
            print(f"✅ Проверка уникальности пройдена: все {len(reviewsList)} отзывов уникальны")
            return True

        # JS: запуск фонового скролла как async task.
        # В Python без потоков — механически вызываем 1 раз перед циклом как "параллельного" не делаем.
        # (Логику основного цикла не меняем ниже.)
        # ВНИМАНИЕ: это место в JS реально параллелит; здесь оставлено как есть без запуска фонового потока.

        while len(reviews) < targetReviews and len(reviewQueue) > 0:
            currentReviewId = reviewQueue.pop(0)

            print(f"\n📝 Парсим отзыв {len(reviews) + 1} из {targetReviews} (ID: {currentReviewId})...")
            print(f"📊 Осталось в очереди: {len(reviewQueue)} отзывов")

            try:
                currentReviewElement = driver.find_element(By.CSS_SELECTOR, f'div[data-id="{currentReviewId}"]')
            except Exception:
                print(f"❌ Не удалось найти элемент отзыва с ID {currentReviewId}, возможно элемент устарел")
                continue

            review = parseReview(driver, currentReviewElement)

            # --- СТОП если ушли ниже нужного диапазона дат ---
            if review is None:
                try:
                    dateContainer = currentReviewElement.find_element(By.CSS_SELECTOR, ".h-ml-12._10cf6rv._19sgipd")
                    dateElement = dateContainer.find_element(By.CSS_SELECTOR, ".h-color-D30._1aja02n._1w66l1f")
                    dateText = dateElement.text
                    reviewDate = parseDate(dateText)

                    from datetime import datetime
                    d = datetime.strptime(reviewDate, "%Y-%m-%d").date()

                    if d < DATE_FROM:
                        print(f"\n🛑 Дошли до отзывов старше {DATE_FROM}. Дальше парсить бессмысленно.")
                        break

                except Exception:
                    pass
            if review:
                reviews.append(review)
                parsedIds.add(currentReviewId)

                print(f"✅ Отзыв {review.get('id')} успешно спарсен")
                print(f"   📅 Дата: {review.get('date')}")
                print(f"   ⭐ Рейтинг: {review.get('rating')}/5")
                print(f"   🔗 Ссылка: {review.get('link')}")
                content = review.get("content") or ""
                print(f"   📄 Контент: {content[:100]}...")

                time.sleep(0.2)

                print(f"🔄 Пересканируем страницу после парсинга отзыва {review.get('id')}...")
                foundNewReviews = updateReviewQueue()

                if foundNewReviews > 0:
                    print(f"🎉 Отлично! После скролла найдено {foundNewReviews} новых отзывов!")
                else:
                    print("ℹ️ Новых отзывов после скролла не найдено")

            else:
                print(f"❌ Не удалось спарсить отзыв {currentReviewId}")

            time.sleep(0.1)

            if len(reviewQueue) == 0 and len(reviews) < targetReviews:
                print("\n⬇️ Очередь пуста, ждем 5 секунд и пересканируем страницу...")
                time.sleep(5)
                newReviewsFound = updateReviewQueue()
                if len(reviewQueue) == 0:
                    print(f"\n🏁 Больше отзывов не найдено. Возможно, это все доступные отзывы. Итого спарсено: {len(reviews)} отзывов")
                    break

        keepScrolling = False
        print("🔍 Выполняем финальную проверку на дубликаты...")
        validateUniqueReviews(reviews)

        print("🎯 РЕЗУЛЬТАТЫ ПАРСИНГА:")
        print("========================")
        for idx, review in enumerate(reviews):
            print(f"Отзыв {idx + 1}:")
            print(f"  ID: {review.get('id')}")
            print(f"  Дата: {review.get('date')}")
            print(f"  Рейтинг: {review.get('rating')}/5")
            print(f"  Ссылка: {review.get('link')}")
            print(f"  Контент: {review.get('content')}")
            print("------------------------")

        print(f"✅ Успешно спарсено {len(reviews)} отзывов из {targetReviews} запрошенных")

        saveReviewsToFile(reviews)

    except Exception as error:
        print("❌ Ошибка при работе парсера:", str(error))
    finally:
        if driver:
            print("🔄 Парсинг завершен, браузер остается открытым для изучения...")
            # driver.quit()  # Закомментировано - браузер остается открытым
            print("✅ Браузер остается доступным")


if __name__ == "__main__":
    parseSravniGazprombank()
    print("🎉 Парсер завершил работу")
    raise SystemExit(0)


__all__ = ["parseSravniGazprombank"]