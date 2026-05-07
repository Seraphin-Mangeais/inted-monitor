import os
import time
import requests
from collections import deque
from datetime import datetime

TELEGRAM_TOKEN = "8397071421:AAHg7_ioahTXX2_aCziaJERJtL4g5CSBqm0"
TELEGRAM_CHAT_ID = "5306743874"
VINTED_EMAIL = os.environ.get("VINTED_EMAIL", "")
VINTED_PASSWORD = os.environ.get("VINTED_PASSWORD", "")
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

BASE = "https://www.vinted.fr"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": "https://www.vinted.fr/",
    "Origin": "https://www.vinted.fr",
}


def make_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def get_csrf_token(session):
    r = session.post(f"{BASE}/oauth/token", timeout=15)
    try:
        return r.json().get("csrf_token", "")
    except Exception:
        return ""


def login(session):
    print("Connexion à Vinted...")
    # Visite initiale pour obtenir les cookies
    session.get(BASE, timeout=15)
    time.sleep(1)

    # Récupère le CSRF token
    r = session.get(f"{BASE}/api/v2/oauth/token_refresh", timeout=15)
    csrf = ""
    try:
        csrf = r.json().get("csrf_token", "")
    except Exception:
        pass

    if not csrf:
        # Essai alternatif
        r2 = session.get(f"{BASE}/web/users/sign_in", timeout=15)
        for cookie in session.cookies:
            if "csrf" in cookie.name.lower():
                csrf = cookie.value
                break

    session.headers.update({"X-Csrf-Token": csrf})

    # Login
    r = session.post(
        f"{BASE}/api/v2/users/login",
        json={
            "user": {
                "login": VINTED_EMAIL,
                "password": VINTED_PASSWORD,
                "remember_me": True,
            }
        },
        timeout=15,
    )
    print(f"Login: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        user = data.get("user", {})
        print(f"Connecté en tant que : {user.get('login', '?')}")
        return True
    else:
        print(f"Échec login: {r.text[:200]}")
        return False


def vinted_get(session, url):
    resp = session.get(url, timeout=20)
    if resp.status_code == 401 or resp.status_code == 403:
        print(f"Token expiré ({resp.status_code}), reconnexion...")
        login(session)
        resp = session.get(url, timeout=20)
    if resp.status_code != 200:
        print(f"HTTP {resp.status_code} | {resp.text[:150]}")
        return None
    try:
        return resp.json()
    except Exception as e:
        print(f"JSON error: {e} | {resp.text[:100]}")
        return None


def fetch_new_listings(session):
    try:
        url = (
            f"{BASE}/api/v2/catalog/items"
            "?page=1&per_page=96&order=newest_first"
            "&status_ids[]=1&status_ids[]=2&status_ids[]=3&status_ids[]=6"
        )
        data = vinted_get(session, url)
        items = data.get("items", []) if data else []
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {len(items)} articles récupérés")
        return items
    except Exception as e:
        print(f"Erreur fetch: {e}")
        return []


def get_market_price(session, item):
    try:
        from urllib.parse import quote
        words = " ".join((item.get("title") or "").split()[:3])
        catalog_id = item.get("catalog_id", "")
        url = (
            f"{BASE}/api/v2/catalog/items"
            f"?search_text={quote(words)}&catalog_ids={catalog_id}"
            f"&per_page=48&order=relevance"
            f"&status_ids[]=1&status_ids[]=2&status_ids[]=3&status_ids[]=6"
        )
        data = vinted_get(session, url)
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


def send_telegram(message):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "disable_web_page_preview": False},
            timeout=10,
        )
    except Exception as e:
        print(f"Erreur Telegram: {e}")


def main():
    if not VINTED_EMAIL or not VINTED_PASSWORD:
        print("❌ VINTED_EMAIL et VINTED_PASSWORD manquants dans les variables d'environnement")
        return

    print("🔍 Démarrage du moniteur Vinted...")
    session = make_session()

    if not login(session):
        print("❌ Connexion impossible, arrêt.")
        return

    send_telegram(
        "✅ Moniteur Vinted démarré !\n"
        "Surveillance toutes les 22s\n"
        "Critères : -45% ou plus · Bon état minimum 🔍"
    )

    counter = 0
    while True:
        try:
            if counter > 0 and counter % 100 == 0:
                login(session)
            counter += 1

            items = fetch_new_listings(session)

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
                url = f"{BASE}/items/{item_id}"

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
