import os
import re
import json
import requests
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))

SCANNER   = "https://scanner.tradingview.com/turkey/scan"
KAP_URL   = "https://www.kap.org.tr/tr/bildirim-sorgu-sonuc?srcbar=Y&cmp=Y&cat=4"
STATE     = "taban_state.json"
TRACK     = "taban_track.json"
SESSIZLIK_SAAT = 24

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}

def telegram_gonder(mesaj):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": mesaj, "disable_web_page_preview": True},
                      timeout=15)
    except Exception as e:
        print("Telegram hatasi:", e)

def seans_icinde_mi():
    s = datetime.now(TRT)
    if s.weekday() >= 5:
        return False
    dk = s.hour * 60 + s.minute
    return (9 * 60 + 45) <= dk <= (18 * 60 + 10)

def tarama_taban():
    body = {
        "columns": ["description", "close", "change", "RSI", "volume", "relative_volume_10d_calc"],
        "filter": [
            {"left": "change", "operation": "greater", "right": -9.9},
            {"left": "change", "operation": "less", "right": -2},
            {"left": "RSI", "operation": "greater", "right": 25},
            {"left": "RSI", "operation": "less", "right": 50},
            {"left": "relative_volume_10d_calc", "operation": "greater", "right": 1.5},
            {"left": "volume", "operation": "greater", "right": 50000},
