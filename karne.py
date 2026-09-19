import os
import json
import requests
from datetime import datetime, date, timedelta, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))
CALLS_FILE = "cagrilar.json"
BENCH_ADAYLARI = ["^XU100", "^XU100.IS", "XU100.IS"]
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
        sym_enc = requests.utils.quote(sym, safe=".")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym_enc}"
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
    gun_sayisi = int(c.get("pencere", GUN))
    ust_sinir = baz_dt + timedelta(days=int(gun_sayisi * 1.5) + 5)
    pencere = [x for x in b if baz_dt < x[0] <= ust_sinir][:gun_sayisi]
    soylenen = c.get("soylenen")
    soy_fark = ((baz - soylenen) / soylenen * 100) if soylenen else None
    promise = ((c["direnç"] - baz) / baz * 100) if c.get("direnç") else None
    if not pencere:
        return {"kod": c["kod"], "baz": baz, "son": baz, "getiri": 0.0, "alfa": 0.0,
                "direnc_gordu": False, "destek_kirildi": False, "stop_gordu": False,
                "ustte": bool(c.get("direnç")) and baz > c["direnç"],
                "soy_fark": soy_fark, "promise": promise,
                "gun": 0, "olgun": False, "bench": None}
    maks = max(x[1] for x in pencere)
    minm = min(x[2] for x in pencere)
    son = pencere[-1][3]
    son_dt = pencere[-1][0]
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
        "soy_fark": soy_fark, "promise": promise,
        "gun": len(pencere), "olgun": len(pencere) >= gun_sayisi, "bench": bench_getiri,
    }

cagrilar = json.load(open(CALLS_FILE, encoding="utf-8")) if os.path.exists(CALLS_FILE) else []
bench = []
for aday in BENCH_ADAYLARI:
    bench = bars_sym(aday)
    if bench:
        print("Bench sembolu calisti:", aday)
        break

ham = [(c, olcu(c, bench)) for c in cagrilar]
beklemede = [c for c, m in ham if m is None]
pairler = [(c, m) for c, m in ham if m]
if not pairler:
    telegram_gonder("🧾 Grup karnesi: veri alinamadi.")
    raise SystemExit

partiler = {}
for c, m in pairler:
    anahtar = (c.get("tarih", "?"), c.get("kaynak", "?"))
    partiler.setdefault(anahtar, []).append((c, m))

satirlar = ["🧾 GRUP KARNESİ v3 — parti parti, piyasa kıyaslı performans"]
for (tarih, kaynak), items in sorted(partiler.items()):
    satirlar.append(f"━━ {tarih} | {kaynak} ━━")
    getiriler = []
    alfalar = []
    hedef_goren = 0
    bench_deger = None
    for c, m in items:
        etiket = []
        if m["direnc_gordu"]:
            etiket.append("🎯 hedef/direnç görüldü")
            hedef_goren += 1
        if m["destek_kirildi"]:
            etiket.append("💥 destek kırıldı")
        if m["stop_gordu"]:
            etiket.append("🛑 stop tetiklendi")
        if m["ustte"]:
            etiket.append("⬆️ zaten hedefin üstündeydi")
        if not etiket:
            etiket.append("➖ yolculuk sürüyor")
        uyari = ""
        if m["soy_fark"] is not None and abs(m["soy_fark"]) > 2:
            uyari = f" ⚠️ söylenen fiyat gerçekle uyuşmuyor ({m['soy_fark']:+.1f}%)"
        promise_txt = f", vaat {m['promise']:+.0f}%" if m["promise"] is not None else ""
        olgunluk = "" if m["olgun"] else f" ({m['gun']}. gün)"
        if m["bench"] is not None:
            bench_deger = m["bench"]
        satirlar.append(f"• {m['kod']}: {m['baz']:.2f} → {m['son']:.2f} ({m['getiri']:+.1f}%, alfa {m['alfa']:+.1f}{promise_txt}) | {' | '.join(etiket)}{olgunluk}{uyari}")
        getiriler.append(m["getiri"])
        alfalar.append(m["alfa"])
    ort = sum(getiriler) / len(getiriler)
    ort_alfa = sum(alfalar) / len(alfalar)
    bench_txt = f"{bench_deger:+.2f}%" if bench_deger is not None else "veri yok"
    satirlar.append(f"📊 Parti: {len(items)} çağrı | hedef gören: {hedef_goren} | ort. {ort:+.2f}% | piyasa {bench_txt} | ALFA {ort_alfa:+.2f}%")
    if len(items) >= 5 and bench_deger is not None:
        if ort_alfa > 2:
            satirlar.append("💬 Bu parti piyasayı belirgin yendi — marifet sinyali.")
        elif ort_alfa >= -2:
            satirlar.append("💬 Bu parti piyasayla aynı sürüklendi — belirgin marifet yok.")
        else:
            satirlar.append("💬 Bu parti piyasadan DAHA kötü — katma değer negatif.")
satirlar.append("📅 Not: Hedef çağrıları 20 işlem günü, seviye çağrıları 10 gün üzerinden ölçülür; alfa piyasa etkisini ayrıştırır.")
satirlar.append("🔎 Bu bir performans ölçümüdür, yatırım tavsiyesi değildir.")
telegram_gonder("\n".join(satirlar))
print("Karne v3 gonderildi")
