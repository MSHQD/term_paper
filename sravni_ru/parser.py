import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# Настройки для Chrome
chrome_options = webdriver.ChromeOptions()
# chrome_options.add_argument("--headless")  # Закомментировано для визуального режима
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--window-size=1920,1080")
chrome_options.add_argument(
    "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Дополнительные настройки безопасности
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_argument("--disable-web-security")
chrome_options.add_argument("--ignore-certificate-errors")
chrome_options.add_argument("--ignore-ssl-errors")
chrome_options.add_argument("--allow-running-insecure-content")


# Конфигурация
CONFIG = {
    "startDate": datetime.fromisoformat("2024-01-01"),
    "endDate": datetime.fromisoformat("2025-05-31"),
    # Убрали фиксированную задержку
}


# Функция для загрузки данных из reviews.json
def load_reviews() -> List[Dict[str, Any]]:
    try:
        with open("./reviews.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as error:
        print("❌ Ошибка при загрузке reviews.json:", str(error))
        return []


# Функция для фильтрации по датам
def filter_by_date(reviews: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for review in reviews:
        try:
            review_date = datetime.fromisoformat(review.get("date"))
        except Exception:
            continue
        if CONFIG["startDate"] <= review_date <= CONFIG["endDate"]:
            out.append(review)
    return out


# Функция для парсинга города и продукта со страницы
def parse_page_data(driver: webdriver.Chrome, url: str) -> Dict[str, Optional[str]]:
    try:
        print(f"  📄 Открываем страницу: {url}")
        driver.get(url)

        # Ждем загрузки хотя бы одного из элементов (продукт или город)
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
            driver.implicitly_wait(0)  # не влияет на sleep, но оставлено как "ничего"
            driver.sleep(0.1)  # механический аналог driver.sleep(100) в JS (ms)
        except Exception:
            print("    ⚠️  Страница не загрузилась полностью")

        product: Optional[str] = None
        city: Optional[str] = None
        status: Optional[str] = None

        # Поиск продукта по классу h-color-D30 h-mr-16 _1w66l1f
        try:
            WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".h-color-D30.h-mr-16._1w66l1f")))
            product_element = driver.find_element(By.CSS_SELECTOR, ".h-color-D30.h-mr-16._1w66l1f")
            product = (product_element.text or "").strip()
        except Exception:
            # Пробуем найти альтернативными селекторами
            try:
                WebDriverWait(driver, 2).until(EC.presence_of_element_located((By.CSS_SELECTOR, '[class*="h-color-D30"]')))
                product_element = driver.find_element(By.CSS_SELECTOR, '[class*="h-color-D30"]')
                product = (product_element.text or "").strip()
            except Exception:
                print("    ⚠️  Продукт не найден")

        # Поиск статуса проблемы и города по классу _1vfu01w _1mxed63 _8km2y3
        try:
            WebDriverWait(driver, 3).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "._1vfu01w._1mxed63._8km2y3")))
            status_elements = driver.find_elements(By.CSS_SELECTOR, "._1vfu01w._1mxed63._8km2y3")

            if len(status_elements) >= 1:
                status = (status_elements[0].text or "").strip()

            if len(status_elements) >= 2:
                city = (status_elements[1].text or "").strip()
            elif len(status_elements) == 1:
                print("    ⚠️  Найден только статус, ищем город альтернативно")

        except Exception:
            # Пробуем найти альтернативными селекторами
            try:
                WebDriverWait(driver, 2).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, '[class*="_1vfu01w"]')))
                status_elements = driver.find_elements(By.CSS_SELECTOR, '[class*="_1vfu01w"]')

                if len(status_elements) >= 1:
                    status = (status_elements[0].text or "").strip()

                if len(status_elements) >= 2:
                    city = (status_elements[1].text or "").strip()
                elif len(status_elements) == 1:
                    print("    ⚠️  Найден только статус альтернативно")
            except Exception:
                print("    ⚠️  Статус и город не найдены")

        return {"product": product, "city": city, "status": status}

    except Exception as error:
        print("❌ Ошибка при парсинге страницы:", str(error))
        return {"product": None, "city": None, "status": None}


# Функция для обработки одного отзыва
def process_review(driver: webdriver.Chrome, review: Dict[str, Any], index: int) -> Dict[str, Any]:
    try:
        print(f"\n🔍 Обрабатываем отзыв {index + 1}: {review.get('id')}")

        page_data = parse_page_data(driver, review.get("link"))
        product = page_data.get("product")
        city = page_data.get("city")
        status = page_data.get("status")

        print(f"  📦 Продукт: {product or 'не найден'}")
        print(f"  🏙️  Город: {city or 'не найден'}")
        print(f"  📋 Статус: {status or 'не найден'}")

        out = dict(review)
        out["product"] = product
        out["city"] = city
        out["status"] = status
        return out

    except Exception as error:
        print(f"❌ Ошибка при обработке отзыва {review.get('id')}: {str(error)}")
        out = dict(review)
        out["product"] = None
        out["city"] = None
        out["status"] = None
        return out


# Функция для сохранения результатов в dataset.json
def save_dataset(data: List[Dict[str, Any]]) -> None:
    try:
        with open("./dataset.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("\n💾 Данные сохранены в dataset.json")
        print(f"📊 Сохранено записей: {len(data)}")
    except Exception as error:
        print("❌ Ошибка при сохранении dataset.json:", str(error))


# Основная функция парсера
def parse_reviews_data() -> List[Dict[str, Any]]:
    driver = None

    try:
        print("🚀 Инициализируем WebDriver...")
        driver = webdriver.Chrome(options=chrome_options)
        print("✅ WebDriver инициализирован")

        print("\n📖 Загружаем данные из reviews.json...")
        all_reviews = load_reviews()
        print(f"📋 Всего отзывов: {len(all_reviews)}")

        print("\n🔍 Фильтруем по датам (01.01.2024 - 31.05.2025)...")
        filtered_reviews = filter_by_date(all_reviews)
        print(f"✅ Отзывов после фильтрации: {len(filtered_reviews)}")

        if len(filtered_reviews) == 0:
            print("⚠️  Нет отзывов в указанном диапазоне дат")
            return []

        reviews_to_process = filtered_reviews
        print(f"\n🧪 Обрабатываем все {len(reviews_to_process)} подходящих отзывов...")

        processed_reviews: List[Dict[str, Any]] = []

        for i in range(len(reviews_to_process)):
            review = reviews_to_process[i]
            processed_review = process_review(driver, review, i)
            processed_reviews.append(processed_review)

        save_dataset(processed_reviews)

        print("\n🎉 Обработка завершена успешно!")
        return processed_reviews

    except Exception as error:
        print("❌ Ошибка при выполнении:", str(error))
        return []
    finally:
        if driver:
            driver.quit()
            print("🔚 WebDriver закрыт")


if __name__ == "__main__":
    parse_reviews_data()


__all__ = ["parse_reviews_data", "load_reviews", "filter_by_date", "save_dataset"]