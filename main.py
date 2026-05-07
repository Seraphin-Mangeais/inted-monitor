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
