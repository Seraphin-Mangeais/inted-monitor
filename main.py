import cloudscraper
import time
from collections import deque
from datetime import datetime

TELEGRAM_TOKEN = "8397071421:AAHg7_ioahTXX2_aCziaJERJtL4g5CSBqm0"
TELEGRAM_CHAT_ID = "5306743874"
DISCOUNT_THRESHOLD = 0.45
MIN_SIMILAR_ITEMS = 5
POLL_INTERVAL = 22

GOOD_CONDITIONS = {1, 2, 3, 6}
CONDITION_LABELS = {
    6: "Neuf avec étiquette ✨",
    1: "Neuf sans étiquette 🏷️",
    2: "Très bon état 👍",
    3: "Bon état 👌",
}

seen_ids = deque(maxlen=3000)
seen_set = set()


def make_scraper():
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    scraper.headers.update({
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer": "https://www.vinted.fr/",
    })
    try:
        r = scraper.get("https://www.vinted.fr", timeout=20)
        print(f"Session init: {r.status_code}")
        time.sleep(2)
    except Exception as e:
        print(f"Erreur session: {e}")
    return scraper


def vinted_get(scraper, url):
    resp = scraper.get(url, timeout=20)
    print(f"GET {resp.status_code} | {resp.headers.get('Content-Type','?')[:40]}")
    if resp.status_code != 200:
        print(f"Body: {resp.text[:300]}")
        return None
    try:
        return resp.json()
    except Exception as e:
        print(f"JSON parse error: {e} | Body: {resp.text[:200]}")
        return None


def fetch_new_listings(scraper):
    try:
        url = (
            "https://www.vinted.fr/api/v2/catalog/items"
            "?page=1&per_page=96&order=newest_first"
            "&status_ids[]=1&status_ids[]=2&status_ids[]=3&status_ids[]=6"
        )
        data = vinted_get(scraper, url)
        items = data.get("items", []) if data else []
        print(f"Articles récupérés: {len(items)}")
        return items
    except Exception as e:
        print(f"Erreur fetch: {e}")
        return []


def get_market_price(scraper, item):
    try:
        words = " ".join((item.get("title") or "").split()[:3])
        catalog_id = item.get("catalog_id", "")
        url = (
            f"https://www.vinted.fr/api/v2/catalog/items"
            f"?search_text={requests_encode(words)}&catalog_ids={catalog_id}"
            f"&per_page=48&order=relevance"
            f"&status_ids[]=1&status_ids[]=2&status_ids[]=3&status_ids[]=6"
        )
        data = vinted_get(scraper, url)
        items = data.get("items", []) if data else []

        prices = [
            float(i["price"])
            for i in items
            if str(i["id"]) != str(item["id"]) and float(i.get("price", 0)) > 0
        ]

        if len(prices) < MIN_SIMILAR_ITEMS:
            return None, 0

        prices.sort()
        trim = max(1, len(prices) // 10)
        trimmed = prices[trim: len(prices) - trim] if len(prices) > 2 * trim else prices
        return sum(trimmed) / len(trimmed), len(prices)
    except Exception as e:
        print(f"Erreur market: {e}")
        return None, 0


def requests_encode(text):
    from urllib.parse import quote
    return quote(text)


def send_telegram(message):
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "disable_web_page_preview": False},
            timeout=10,
        )
    except Exception as e:
        print(f"Erreur Telegram: {e}")


def main():
    print("🔍 Démarrage du moniteur Vinted...")
    scraper = make_scraper()
    counter = 0

    send_telegram(
        "✅ Moniteur Vinted démarré !\n"
        "Surveillance toutes les 22s\n"
        "Critères : -45% ou plus · Bon état minimum 🔍"
    )

    while True:
        try:
            if counter > 0 and counter % 80 == 0:
                scraper = make_scraper()
            counter += 1

            items = fetch_new_listings(scraper)
            ts = datetime.now().strftime("%H:%M:%S")

            for item in items:
                item_id = str(item.get("id", ""))
                if not item_id or item_id in seen_set:
                    continue

                seen_ids.append(item_id)
                seen_set.add(item_id)

                condition = item.get("status_id") or item.get("item_condition_id")
                if condition not in GOOD_CONDITIONS:
                    continue

                try:
                    price = float(item.get("price", 0))
                except Exception:
                    continue

                if price <= 0:
                    continue

                avg_price, count = get_market_price(scraper, item)
                if not avg_price:
                    continue

                discount = (avg_price - price) / avg_price
                if discount < DISCOUNT_THRESHOLD:
                    continue

                label = CONDITION_LABELS.get(condition, "Bon état")
                url = f"https://www.vinted.fr/items/{item_id}"

                msg = (
                    f"🔥 BONNE AFFAIRE DÉTECTÉE !\n\n"
                    f"📦 {item.get('title', 'Article')}\n"
                    f"💰 Prix : {price:.0f}€\n"
                    f"📊 Marché : ~{avg_price:.0f}€ ({count} articles)\n"
                    f"📉 Réduction : -{discount * 100:.0f}%\n"
                    f"✨ État : {label}\n"
                    f"🔗 {url}"
                )

                print(f"✅ ALERTE: {item.get('title')} — {price:.0f}€ vs {avg_price:.0f}€ (-{discount*100:.0f}%)")
                send_telegram(msg)
                time.sleep(0.5)

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("Arrêt.")
            break
        except Exception as e:
            print(f"Erreur: {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()
