import os
import json
import requests
from datetime import datetime, date, timedelta, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))
CALLS_FILE = "cagrilar.json"
GUN = 10   # is gunu penceresi

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}

def telegram_gonder(mesaj):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": mesaj, "disable_web_page_preview": True},
                      timeout=15)
    except Exception as e:
        print("Telegram hatasi:", e)

def bars(kod):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{kod}.IS"
        r = requests.get(url, params={"range": "6mo", "interval": "1d"}, headers=HEADERS, timeout=30)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        ts = res.get("timestamp", [])
        q = res["indicators"]["quote"][0]
        hi, lo, cl = q.get("high", []), q.get("low", []), q.get("close", [])
        out = []
        for t, h, l, c in zip(ts, hi, lo, cl):
            if c is None:
                continue
            out.append((datetime.fromtimestamp(t, TRT).date(),
                        float(h) if h is not None else float(c),
                        float(l) if l is not None else float(c),
                        float(c)))
        return out
    except Exception as e:
        print("Bars hatasi:", kod, e)
        return []

def olcu(c):
    b = bars(c["kod"])
    if not b:
        return None
    ct = date.fromisoformat(c["tarih"])
    baz_dt = baz = None
    for dt, h, l, cl in b:
        if dt >= ct:
            baz_dt, baz = dt, cl
            break
    if baz is None:
        return None
    pencere = [x for x in b if baz_dt < x[0] <= baz_dt + timedelta(days=16)][:GUN]
    if not pencere:
        return {"kod": c["kod"], "baz": baz, "son": baz, "getiri": 0.0,
                "direnc_gordu": False, "destek_kirildi": False, "stop_gordu": False,
                "gun": 0, "olgun": False}
    maks = max(x[1] for x in pencere)
    minm = min(x[2] for x in pencere)
    son = pencere[-1][3]
    return {
        "kod": c["kod"], "baz": baz, "son": son,
        "getiri": (son - baz) / baz * 100,
        "direnc_gordu": bool(c.get("direnç")) and maks >= c["direnç"],
        "destek_kirildi": bool(c.get("destek")) and minm < c["destek"],
        "stop_gordu": bool(c.get("stop")) and minm <= c["stop"],
        "gun": len(pencere), "olgun": len(pencere) >= GUN,
    }

cagrilar = json.load(open(CALLS_FILE, encoding="utf-8")) if os.path.exists(CALLS_FILE) else []
sonuclar = [m for m in (olcu(c) for c in cagrilar) if m]
if not sonuclar:
    telegram_gonder("🧾 Grup karnesi: veri alinamadi, Yahoo finans yanit vermedi.")
    raise SystemExit

satirlar = ["🧾 GRUP KARNESİ — 7 Eylül çağrıları, ilk 10 işlem günü"]
dg = dk = sg = 0
getiriler = []
for m in sonuclar:
    etiket = []
    if m["direnc_gordu"]:
        etiket.append("🚀 direnç görüldü")
        dg += 1
    if m["destek_kirildi"]:
        etiket.append("💥 destek kırıldı")
        dk += 1
    if m["stop_gordu"]:
        etiket.append("🛑 stop tetiklendi")
        sg += 1
    if not etiket:
        etiket.append("➖ bant içinde")
    olgunluk = "" if m["olgun"] else f" ({m['gun']}. gün)"
    satirlar.append(f"• {m['kod']}: {m['baz']:.2f} → {m['son']:.2f} ({m['getiri']:+.1f}%) | {' | '.join(etiket)}{olgunluk}")
    getiriler.append(m["getiri"])

ort = sum(getiriler) / len(getiriler)
satirlar.append(f"📊 TOPLU: {len(sonuclar)} çağrı | direnç gören: {dg} | destek kıran: {dk} | stop: {sg} | ort. getiri: {ort:+.2f}%")
if len(sonuclar) >= 5:
    if ort > 1 and dg > dk:
        satirlar.append("💬 Yorum: Çağrılar 10 günde ortalamada pozitif katkı yaptı — takip edilebilir.")
    elif ort < 0:
        satirlar.append("💬 Yorum: Çağrılar ortalamada kaybettirdi — grubun marifeti şüpheli, temkinli ol.")
    else:
        satirlar.append("💬 Yorum: Karışık tablo — belirgin bir marifet yok; seviyeleri sadece referans al.")
satirlar.append("🔎 Bu bir performans ölçümüdür, yatırım tavsiyesi değildir.")
telegram_gonder("\n".join(satirlar))
print("Karne gonderildi")
