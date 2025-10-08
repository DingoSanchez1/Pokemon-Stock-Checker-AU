#!/usr/bin/env python3
"""
Pokemon TCG stock/anticipated checker (supports Hotmail/Outlook SMTP).
Place this file, requirements.txt, and config.json in the same repo.

Environment variables (set these as GitHub Secrets in Actions):
  SMTP_SERVER (default: smtp.office365.com)
  SMTP_PORT (default: 587)
  EMAIL_ADDRESS (your Hotmail/Outlook address - sender)
  EMAIL_PASSWORD (your Hotmail account password or app password)
  RECIPIENT_EMAIL (optional override; otherwise uses config.json recipient_email)
"""

import os
import json
import re
import time
from pathlib import Path
from typing import Dict
import requests
from bs4 import BeautifulSoup
import smtplib
from email.message import EmailMessage

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
LAST_STATUS_PATH = BASE_DIR / "last_status.json"

# simple keyword lists - tweak as needed
IN_STOCK_WORDS = [
    "in stock", "add to cart", "add to bag", "add to basket", "add to trolley",
    "available now", "available to buy", "available", "buy now", "add to cart", "add"
]
ANTICIPATED_WORDS = [
    "pre-order", "preorder", "pre order", "coming soon", "available soon",
    "available for pre-order", "expected", "back in stock", "restock", "notify me",
    "release date", "available from"
]
OUT_OF_STOCK_WORDS = [
    "out of stock", "sold out", "currently unavailable", "unavailable", "not available"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}

def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    else:
        raise FileNotFoundError("config.json missing. Create one with product URLs.")

def load_last_status() -> Dict[str, str]:
    if LAST_STATUS_PATH.exists():
        return json.loads(LAST_STATUS_PATH.read_text(encoding="utf-8"))
    return {}

def save_last_status(d: Dict[str, str]):
    LAST_STATUS_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")

def fetch_html(url, timeout=20):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def check_json_ld_for_availability(html: str):
    patterns = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                          html, flags=re.I|re.S)
    for p in patterns:
        try:
            data = json.loads(p.strip())
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            offers = node.get("offers") if isinstance(node, dict) else None
            if offers:
                offer_list = offers if isinstance(offers, list) else [offers]
                for off in offer_list:
                    avail = off.get("availability") or off.get("Availability") or ""
                    if isinstance(avail, str) and "instock" in avail.lower():
                        return "in_stock"
                    if isinstance(avail, str) and "outofstock" in avail.lower():
                        return "out_of_stock"
    return None

def detect_status_from_html(html: str):
    if not html:
        return "unknown"
    low = html.lower()
    st = check_json_ld_for_availability(html)
    if st:
        return st
    for w in IN_STOCK_WORDS:
        if w in low:
            return "in_stock"
    for w in ANTICIPATED_WORDS:
        if w in low:
            return "anticipated"
    for w in OUT_OF_STOCK_WORDS:
        if w in low:
            return "out_of_stock"
    soup = BeautifulSoup(html, "html.parser")
    for btn in soup.find_all(["button","a","input"]):
        txt = (btn.get_text() or "") + " " + " ".join([str(x) for x in btn.attrs.values()])
        txt = txt.lower()
        if any(x in txt for x in IN_STOCK_WORDS):
            return "in_stock"
        if any(x in txt for x in ANTICIPATED_WORDS):
            return "anticipated"
    return "unknown"

def send_email(subject: str, body: str, sender: str, password: str, recipient: str,
               smtp_server: str, smtp_port: int):
    if not sender or not password or not recipient:
        print("Email not sent: missing credentials.")
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body)
    try:
        # Use STARTTLS (suitable for smtp.office365.com / outlook/hotmail)
        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(sender, password)
            smtp.send_message(msg)
        print(f"Email sent to {recipient}: {subject}")
        return True
    except Exception as e:
        print("Failed to send email:", e)
        return False

def main():
    config = load_config()
    products = config.get("products", [])
    recipient_from_config = config.get("recipient_email")
    last = load_last_status()
    changes = []

    smtp_server = os.getenv("SMTP_SERVER", "smtp.office365.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    email_addr = os.getenv("EMAIL_ADDRESS")  # sender
    email_pass = os.getenv("EMAIL_PASSWORD")
    recipient_env = os.getenv("RECIPIENT_EMAIL")
    recipient = recipient_env or recipient_from_config or email_addr

    for p in products:
        label = p.get("label") or p.get("url")
        url = p.get("url")
        print("Checking:", label, url)
        html = fetch_html(url)
        status = detect_status_from_html(html)
        prev = last.get(url)
        print(" -> status:", status, "previous:", prev)
        if status in ("in_stock", "anticipated") and prev != status:
            changes.append({"label": label, "url": url, "status": status})
        last[url] = status
        time.sleep(1.5)

    if changes:
        subject = f"Pokemon stock alert: {len(changes)} change(s)"
        lines = []
        for c in changes:
            lines.append(f"{c['label']}\n{c['url']}\nStatus: {c['status']}\n")
        body = "\n".join(lines)
        ok = send_email(subject, body, email_addr, email_pass, recipient, smtp_server, smtp_port)
        if not ok:
            print("Email failed; check credentials and logs.")
    else:
        print("No changes requiring alert.")
    save_last_status(last)

if __name__ == "__main__":
    main()
