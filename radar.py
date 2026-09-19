import os
import re
import json
import requests
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))

SCANNER     = "https://scanner.tradingview.com/turkey/scan"
KAP_URL     = "https://www.kap.org.tr/tr/bildirim-sorgu-sonuc?srcbar=Y&cmp=Y&cat=4"
RADAR_FILE  = "radar.json"
RADAR_TRACK = "radar_track.json"

ESIK_YUZDE = 3.0
ESIK_HACIM = 2.0
SESSIZLIK_SAAT = 6
MAKS_UYARI = 5

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
    return (9 * 60 + 40) <= dk <= (18 * 60 + 30)

def son_kapanis(kod):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{kod}.IS"
        r = requests.get(url, params={"range": "5d", "interval": "1d"}, headers=HEADERS, timeout=30)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        closes = [c for c in res["indicators"]["quote"][0].get("close", []) if c is not None]
        return float(closes[-1]) if closes else None
    except Exception as e:
        print("Son kapanis hatasi:", kod, e)
        return None

def tarama(yon):
    op = "egreater" if yon == "up" else "eless"
    sag = ESIK_YUZDE if yon == "up" else -ESIK_YUZDE
    body = {
        "columns": ["description", "close", "change", "volume", "average_volume_10d_calc", "average_volume"],
        "filter": [{"left": "change", "operation": op, "right": sag}],
        "sort": {"sortBy": "change", "sortOrder": "desc" if yon == "up" else "asc"},
        "range": [0, 25],
        "options": {"lang": "tr"},
    }
    r = requests.post(SCANNER, json=body, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])

def kap_son24_kodlar(saat=24):
    kodlar = set()
    try:
        r = requests.get(KAP_URL, headers=HEADERS, timeout=60)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        simdi = datetime.now(TRT)
        for tr in soup.find_all("tr"):
            hucreler = [h.get_text(" ", strip=True) for h in tr.find_all(["td", "th"])]
            metin = " | ".join(hucreler)
            tm = re.search(r"(Bugün|Dün|\d{2}\.\d{2}\.\d{4})\s+(\d{1,2}):(\d{2})", metin)
            if not tm:
                continue
            if tm.group(1) == "Bugün":
                dt = simdi.replace(hour=int(tm.group(2)), minute=int(tm.group(3)))
            elif tm.group(1) == "Dün":
                dt = (simdi - timedelta(days=1)).replace(hour=int(tm.group(2)), minute=int(tm.group(3)))
            else:
                g, a, y = tm.group(1).split(".")
                dt = datetime(int(y), int(a), int(g), int(tm.group(2)), int(tm.group(3)), tzinfo=TRT)
            if simdi - dt > timedelta(hours=saat):
                continue
            for hucre in hucreler:
                if re.fullmatch(r"[A-Z0-9]{3,6}(?: [A-Z0-9]{3,6})*(?: \(\+\d+\))?", hucre):
                    for tok in re.findall(r"[A-Z0-9]{3,6}", hucre):
                        kodlar.add(tok)
    except Exception as e:
        print("KAP capraz kontrol hatasi:", e)
    return kodlar

def state_oku():
    try:
        with open(RADAR_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"alerts": {}}

def state_yaz(d):
    with open(RADAR_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)

def radar_track_oku():
    try:
        with open(RADAR_TRACK, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def radar_track_yaz(l):
    with open(RADAR_TRACK, "w", encoding="utf-8") as f:
        json.dump(l, f, ensure_ascii=False)

def radar_takip_kontrol():
    liste = radar
