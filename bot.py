import requests
import time
import random
import logging
import json
import os
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
CHECK_INTERVAL = 300  # seconds (300 = 5 minutes)

SEEN_FILE = os.getenv("SEEN_FILE", "seen_products.json")

# -------------------------
# Persistence (avoid spam)
# -------------------------
def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


# -------------------------
# Retry helper
# -------------------------
def _get_with_retry(session, url, max_retries=3, timeout=10):
    for attempt in range(max_retries):
        try:
            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt + random.uniform(0, 1)
            logger.warning(f"Retry {attempt + 1}/{max_retries} for {url}")
            time.sleep(wait)


# -------------------------
# Scraper
# -------------------------
def broken_binding_checks():
    urls = [
        {"url": "https://thebrokenbindingsub.com/collections/to-the-stars", "store": "To The Stars"},
        {"url": "https://thebrokenbindingsub.com/collections/the-infirmary", "store": "The Infirmary"},
        {"url": "https://thebrokenbindingsub.com/collections/dragons-hoard", "store": "Dragon's Hoard"},
        {"url": "https://thebrokenbindingsub.com/collections/the-graveyard", "store": "The Graveyard"},
    ]

    product_list = []

    with requests.Session() as session:
        session.headers.update({
            "User-Agent": "Mozilla/5.0"
        })

        for entry in urls:
            base_url = entry["url"]
            store = entry["store"]
            page = 1

            while True:
                try:
                    response = _get_with_retry(session, f"{base_url}?page={page}")
                except Exception:
                    break

                soup = BeautifulSoup(response.content, "html.parser")
                items = soup.find_all("li", class_="grid__item")

                if not items:
                    break

                for product in items:
                    heading = product.find("h3", class_="card__heading")
                    if not heading:
                        continue

                    link_tag = heading.find("a")
                    if not link_tag:
                        continue

                    name = link_tag.get_text(strip=True)
                    link = "https://thebrokenbindingsub.com" + link_tag.get("href")

                    try:
                        product_page = _get_with_retry(session, link)
                        psoup = BeautifulSoup(product_page.content, "html.parser")

                        cart_button = psoup.find("button", class_="product-form__submit")
                        in_stock = cart_button and "Sold out" not in cart_button.get_text()

                    except Exception:
                        continue

                    price_span = product.find("span", class_="price-item")
                    price = price_span.get_text(strip=True) if price_span else "N/A"

                    product_list.append({
                        "name": name,
                        "price": price,
                        "store": store,
                        "link": link,
                        "in_stock": in_stock
                    })

                page += 1

    return product_list


# -------------------------
# Discord sender
# -------------------------
def send_discord(new_items):
    if not new_items:
        return

    for item in new_items:
        message = (
            f"🚨 **{item['name']}**\n"
            f"💰 {item['price']}\n"
            f"🏪 {item['store']}\n"
            f"🔗 {item['link']}"
        )

        try:
            requests.post(WEBHOOK_URL, json={"content": message})
        except Exception as e:
            logger.error(f"Discord send failed: {e}")


# -------------------------
# Main loop
# -------------------------
def run_bot():
    seen = load_seen()

    logger.info("Bot started...")

    while True:
        try:
            products = broken_binding_checks()

            new_items = []
            for p in products:
                if p["in_stock"] and p["link"] not in seen:
                    new_items.append(p)
                    seen.add(p["link"])

            if new_items:
                logger.info(f"Found {len(new_items)} new items")
                send_discord(new_items)
                save_seen(seen)
            else:
                logger.info("No new items")

        except Exception as e:
            logger.error(f"Error in loop: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    run_bot()