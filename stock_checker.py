#!/usr/bin/env python3
"""Check stock status for a product page and email when it comes back in stock.

Configuration is via environment variables (set them before running, or
let the scheduled task inherit them):

  STOCK_PRODUCT_URL    Product page URL (defaults to the Lenovo IdeaPad Slim 5
                        page below if not set)
  STOCK_SMTP_USER       Sender Gmail address, e.g. meghnachandru4@gmail.com
  STOCK_SMTP_PASSWORD   Gmail "app password" (NOT your normal Gmail password)
  STOCK_TO_EMAIL        Where to send the alert (defaults to STOCK_SMTP_USER)

Only sends an email when availability changes from not-in-stock to in-stock,
so you don't get spammed every run. State is remembered in stock_state.json
next to this script.
"""
import json
import os
import re
import smtplib
import sys
import urllib.error
import urllib.request
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

DEFAULT_URL = (
    "https://www.lenovo.com/in/outletin/en/p/laptops/ideapad/ideapad-s-series/"
    "lenovo-ideapad-slim-5-gen-10-14-inch-amd/83hxr001r0"
)

PRODUCT_URL = os.environ.get("STOCK_PRODUCT_URL", DEFAULT_URL)

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / "stock_state.json"
LOG_FILE = SCRIPT_DIR / "stock_check.log"

SMTP_HOST = os.environ.get("STOCK_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("STOCK_SMTP_PORT", "465"))
SMTP_USER = os.environ.get("STOCK_SMTP_USER")
SMTP_PASSWORD = os.environ.get("STOCK_SMTP_PASSWORD")
TO_EMAIL = os.environ.get("STOCK_TO_EMAIL", SMTP_USER)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}


def log(message: str) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    line = f"[{timestamp}] {message}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def fetch_page(url: str) -> str:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def extract_product_offer(html: str):
    blocks = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    for block in blocks:
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            if item.get("@type") == "Product" and "offers" in item:
                offers = item["offers"]
                offers = offers[0] if isinstance(offers, list) else offers
                return {
                    "name": item.get("name"),
                    "price": offers.get("price"),
                    "currency": offers.get("priceCurrency"),
                    "availability": offers.get("availability", ""),
                }
    return None


def load_last_status():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8")).get("availability")
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_status(status: str) -> None:
    STATE_FILE.write_text(
        json.dumps({"availability": status, "checked_at": datetime.now().isoformat()}),
        encoding="utf-8",
    )


def send_email(subject: str, body: str) -> None:
    if not SMTP_USER or not SMTP_PASSWORD or not TO_EMAIL:
        log(
            "Email not sent: missing STOCK_SMTP_USER / STOCK_SMTP_PASSWORD / "
            "STOCK_TO_EMAIL environment variables."
        )
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = TO_EMAIL
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [TO_EMAIL], msg.as_string())
    log(f"Email sent to {TO_EMAIL}: {subject}")


def main() -> int:
    try:
        html = fetch_page(PRODUCT_URL)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        log(f"Failed to fetch product page: {exc}")
        return 1

    offer = extract_product_offer(html)
    if offer is None:
        log("Could not find product/offer data on the page (site layout may have changed).")
        return 1

    availability = offer["availability"] or ""
    in_stock = availability.endswith("InStock")
    previous = load_last_status()
    name = offer.get("name") or "Product"
    price = offer.get("price")
    currency = offer.get("currency") or ""

    log(f"{name}: availability={availability}, price={price} {currency}".strip())

    if in_stock and previous != availability:
        send_email(
            subject=f"IN STOCK: {name}",
            body=(
                f"The product is now in stock.\n\n"
                f"Link: {PRODUCT_URL}\n"
            ),
        )
    elif not in_stock:
        log("Still out of stock / unavailable.")

    save_status(availability)
    return 0


if __name__ == "__main__":
    sys.exit(main())
