import requests
import time
from collections import deque
from datetime import datetime

TELEGRAM_TOKEN = "8397071421:AAHg7_ioahTXX2_aCziaJERJtL4g5CSBqm0"
TELEGRAM_CHAT_ID = "5306743874"
DISCOUNT_THRESHOLD = 0.45
MIN_SIMILAR_ITEMS = 5
POLL_INTERVAL = 22  # secondes entre chaque scan

GOOD_CONDITIONS = {1, 2, 3, 6}
CONDITION_LABELS = {
    6: "Neuf avec étiquette ✨",
    1: "Neuf sans étiquette 🏷️",
    2: "Très bon état 👍",
    3: "Bon état 👌",
}

seen_ids = deque(maxlen=3000)
seen_set = set()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.vinted.fr/",
    "Origin": "https://www.vinted.fr",
    "DNT": "1",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


def get_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        r = session.get("https://www.vinted.fr", timeout=15)
        print(f"Session init: {r.status_code}")
        time.sleep(2)
        session.get("https://www.vinted.fr/catalog", timeout=15)
        time.sleep(1)
    except Exception as e:
        print(f"Erreur session: {e}")
    return session


def vinted_get(session, url, params):
    resp = session.get(url, params=params, timeout=15)
    if resp.status_code != 200:
        print(f"HTTP {resp.status_code} — {url}")
        return None
    ct = resp.headers.get("Content-Type", "")
    if "json" not in ct:
        print(f"Réponse non-JSON ({ct[:50]}), Vinted bloque probablement la requête")
        return None
    return resp.json()


def fetch_new_listings(session):
    try:
        data = vinted_get(
            session,
            "https://www.vinted.fr/api/v2/catalog/items",
            {
                "page": 1,
                "per_page": 96,
                "order": "newest_first",
                "status_ids[]": [1, 2, 3, 6],
            },
        )
        return data.get("items", []) if data else []
    except Exception as e:
        print(f"Erreur fetch: {e}")
        return []


def get_market_price(session, item):
    try:
        words = " ".join((item.get("title") or "").split()[:3])
        catalog_id = item.get("catalog_id", "")

        data = vinted_get(
            session,
            "https://www.vinted.fr/api/v2/catalog/items",
            {
                "search_text": words,
                "catalog_ids": catalog_id,
                "per_page": 48,
                "order": "relevance",
                "status_ids[]": [1, 2, 3, 6],
            },
        )
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
        trimmed = prices[trim : len(prices) - trim] if len(prices) > 2 * trim else prices
        return sum(trimmed) / len(trimmed), len(prices)
    except Exception as e:
        print(f"Erreur market: {e}")
        return None, 0


def send_telegram(message):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": False,
            },
            timeout=10,
        )
    except Exception as e:
        print(f"Erreur Telegram: {e}")


def main():
    print("🔍 Démarrage du moniteur Vinted...")
    session = get_session()
    counter = 0

    send_telegram(
        "✅ Moniteur Vinted démarré !\n"
        "Surveillance en temps réel toutes les 30s\n"
        "Critères : -45% ou plus · Bon état minimum 🔍"
    )

    while True:
        try:
            if counter % 100 == 0:
                session = get_session()
            counter += 1

            items = fetch_new_listings(session)
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] {len(items)} articles récupérés")

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

                avg_price, count = get_market_price(session, item)
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
