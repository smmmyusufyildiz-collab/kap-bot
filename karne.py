import os
import json
import requests
from datetime import datetime, date, timedelta, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))
CALLS_FILE = "cagrilar.json"
BENCH_SYM  = "^XU100.IS"   # BIST 100
GUN = 10

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}

def telegram_gonder(mesaj):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": mesaj, "disable_web_page_preview": True},
                      timeout=15)
    except Exception as e:
        print("Telegram hatasi:", e)

def bars_sym(sym):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
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
        print("Bars hatasi:", sym, e)
        return []

def bars(kod):
    return bars_sym(f"{kod}.IS")

def olcu(c, bench):
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
        return {"kod": c["kod"], "baz": baz, "son": baz, "getiri": 0.0, "alfa": 0.0,
                "direnc_gordu": False, "destek_kirildi": False, "stop_gordu": False,
                "ustte": bool(c.get("direnç")) and baz > c["direnç"],
                "gun": 0, "olgun": False, "bench": None}
    maks = max(x[1] for x in pencere)
    minm = min(x[2] for x in pencere)
    son = pencere[-1][3]
    son_dt = pencere[-1][0]
    # ayni pencerede piyasa getirisi
    bench_getiri = None
    if bench:
        bb = [x for x in bench if x[0] <= baz_dt]
        bs = [x for x in bench if x[0] <= son_dt]
        if bb and bs:
            bench_getiri = (bs[-1][3] - bb[-1][3]) / bb[-1][3] * 100
    getiri = (son - baz) / baz * 100
    alfa = getiri - bench_getiri if bench_getiri is not None else 0.0
    return {
        "kod": c["kod"], "baz": baz, "son": son, "getiri": getiri, "alfa": alfa,
        "direnc_gordu": bool(c.get("direnç")) and baz <= c["direnç"] and maks >= c["direnç"],
        "destek_kirildi": bool(c.get("destek")) and baz >= c["destek"] and minm < c["destek"],
        "stop_gordu": bool(c.get("stop")) and minm <= c["stop"],
        "ustte": bool(c.get("direnç")) and baz > c["direnç"],
        "gun": len(pencere), "olgun": len(pencere) >= GUN, "bench": bench_getiri,
    }

cagrilar = json.load(open(CALLS_FILE, encoding="utf-8")) if os.path.exists(CALLS_FILE) else []
bench = bars_sym(BENCH_SYM)
sonuclar = [m for m in (olcu(c, bench) for c in cagrilar) if m]
if not sonuclar:
    telegram_gonder("🧾 Grup karnesi: veri alinamadi.")
    raise SystemExit

satirlar = ["🧾 GRUP KARNESİ v2 — 7 Eylül çağrıları, ilk 10 işlem günü (piyasa kıyaslı)"]
dg = dk = sg = 0
getiriler = []
alfalar = []
bench_deger = None
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
    if m["ustte"]:
        etiket.append("⬆️ çağrıda zaten direncin üstündeydi")
    if not etiket:
        etiket.append("➖ bant içinde")
    olgunluk = "" if m["olgun"] else f" ({m['gun']}. gün)"
    if m["bench"] is not None:
        bench_deger = m["bench"]
    satirlar.append(f"• {m['kod']}: {m['baz']:.2f} → {m['son']:.2f} ({m['getiri']:+.1f}%, alfa {m['alfa']:+.1f}%) | {' | '.join(etiket)}{olgunluk}")
    getiriler.append(m["getiri"])
    alflar = alfalar  # yer tutucu
    alfalar.append(m["alfa"])

ort = sum(getiriler) / len(getiriler)
ort_alfa = sum(alfalar) / len(alfalar)
satirlar.append(f"📊 TOPLU: {len(sonuclar)} çağrı | direnç: {dg} | destek kıran: {dk} | stop: {sg}")
satirlar.append(f"📈 Çağrı ort.: {ort:+.2f}% | 📉 Piyasa (BIST100) aynı pencere: {bench_deger:+.2f}% | ⚖️ ALFA: {ort_alfa:+.2f}%")
if len(sonuclar) >= 5:
    if ort_alfa > 2:
        satirlar.append("💬 Yorum: Çağrılar piyasayı belirgin yendi — marifet sinyali var.")
    elif ort_alfa >= -2:
        satirlar.append("💬 Yorum: Çağrılar piyasanla aynı sürüklendi — olağanüstü hafta etkisi ayrıştırıldı; belirgin marifet ya da belirgin beceriksizlik yok.")
    else:
        satirlar.append("💬 Yorum: Piyasadan DAHA kötü — grubun katma değeri negatif, temkinli ol.")
satirlar.append("📅 Not: Pencere piyasa geneli olağanüstü hareketleri içerir; alfa sütunu onları ayrıştırır.")
satirlar.append("🔎 Bu bir performans ölçümüdür, yatırım tavsiyesi değildir.")
telegram_gonder("\n".join(satirlar))
print("Karne v2 gonderildi")
