import os
import re
import json
import requests
from datetime import datetime, timedelta, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))

STATE = "onay_state.json"
CAGRI = "cagrilar.json"
GECERLILIK_SAAT = 72

def tg(mesaj):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": mesaj, "disable_web_page_preview": True},
                      timeout=15)
    except Exception as e:
        print("Telegram hatasi:", e)

def oku(path, bos=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return [] if bos is None else bos

def yaz(path, veri):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False)

def updates_get(offset):
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                         params={"offset": offset, "limit": 100}, timeout=30)
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception as e:
        print("getUpdates hatasi:", e)
        return []

def fiyat(kod):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{kod}.IS"
        r = requests.get(url, params={"range": "5d", "interval": "1d"},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        meta = res.get("meta", {})
        p = meta.get("regularMarketPrice")
        if p:
            return float(p)
        closes = [c for c in res["indicators"]["quote"][0].get("close", []) if c is not None]
        return float(closes[-1]) if closes else None
    except Exception as e:
        print("Fiyat hatasi:", kod, e)
        return None

def tur(manuel=False):
    state = oku(STATE, {"last": 0, "onaylar": {}, "logged": []})
    if not isinstance(state, dict):
        state = {"last": 0, "onaylar": {}, "logged": []}
    last = state.get("last", 0)
    for u in updates_get(last + 1):
        last = max(last, u.get("update_id", last))
        msg = u.get("message") or {}
        text = (msg.get("text") or "").strip().upper()
        m = re.fullmatch(r"([BC]{1,2})\+\s+([A-Z0-9]{3,6})", text)
        if m:
            kaynaklar, kod = m.group(1), m.group(2)
            rec = state.setdefault("onaylar", {}).setdefault(kod, {})
            for ch in kaynaklar:
                rec[ch] = datetime.now(TRT).isoformat()
            print("Onay kaydi:", kaynaklar, kod)
            continue
        if text == "LISTE":
            satirlar = ["🤝 ONAY DEFTERİ:"]
            onaylar = state.get("onaylar", {})
            if not onaylar:
                satirlar.append("(boş — format: B+ KOD / C+ KOD / BC+ KOD)")
            for kod, rec in onaylar.items():
                b, c = rec.get("B"), rec.get("C")
                satirlar.append(f"• {kod}: B={b[:16] if b else '-'} | C={c[:16] if c else '-'}")
            tg("\n".join(satirlar))
    state["last"] = last

    simdi = datetime.now(TRT)
    eklenen = []
    for kod, rec in state.get("onaylar", {}).items():
        b, c = rec.get("B"), rec.get("C")
        if not b or not c:
            continue
        tb, tc = datetime.fromisoformat(b), datetime.fromisoformat(c)
        if simdi - tb > timedelta(hours=GECERLILIK_SAAT) or simdi - tc > timedelta(hours=GECERLILIK_SAAT):
            continue
        anahtar = f"{kod}|{b[:10]}|{c[:10]}"
        if anahtar in state.get("logged", []):
            continue
        p = fiyat(kod)
        if not p:
            continue
        cagrilar = oku(CAGRI, [])
        cagrilar.append({"tarih": simdi.date().isoformat(),
                         "kaynak": "ÇİFT ONAY (B+C)", "kod": kod,
                         "soylenen": round(p, 2), "pencere": 10})
        yaz(CAGRI, cagrilar)
        state.setdefault("logged", []).append(anahtar)
        eklenen.append((kod, p, tb, tc))
    yaz(STATE, state)

    for kod, p, tb, tc in eklenen:
        tg(
            f"🤝 ÇİFT ONAY — B ve C aynı hissede buluştu\n"
            f"🏢 {kod}\n"
            f"💰 Referans fiyat: {p:.2f} TL\n"
            f"🕐 B onay: {tb.strftime('%d %b %H:%M')} | C onay: {tc.strftime('%d %b %H:%M')}\n"
            f"📒 Deftere işlendi: kaynak 'ÇİFT ONAY (B+C)' — 10 işlem günü sonra hüküm karnede.")
    if manuel and not eklenen:
        tg("🤝 ONAY TEST: şu an çift onay yok. Format: 'B+ KOD', 'C+ KOD' veya 'BC+ KOD'; durum için 'LISTE'.")
    print("Tur bitti, yeni cift onay:", len(eklenen))

tur(manuel=(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"))
