import os
import json
import requests
from datetime import datetime, timedelta, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))

SCANNER = "https://scanner.tradingview.com/turkey/scan"
STATE   = "taban_state.json"
TRACK   = "taban_track.json"
SESSIZLIK_SAAT = 24
SONUC_SAAT = 48

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}

def telegram_gonder(mesaj):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": mesaj, "disable_web_page_preview": True},
                      timeout=15)
    except Exception as e:
        print("Telegram hatasi:", e)

def oku(path, bos):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return bos

def yaz(path, veri):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False)

def tarama(columns, filters, adet=40):
    body = {
        "columns": columns,
        "filter": filters,
        "sort": {"sortBy": "change", "sortOrder": "desc"},
        "range": [0, adet],
        "options": {"lang": "tr"},
    }
    try:
        r = requests.post(SCANNER, json=body, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        print("Scanner hatasi:", e)
        return []

def kapanislar(kod, range_="6mo"):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{kod}.IS"
        r = requests.get(url, params={"range": range_, "interval": "1d"}, headers=HEADERS, timeout=20)
        r.raise_for_status()
        q = r.json()["chart"]["result"][0]["indicators"]["quote"][0]
        return [c for c in q.get("close", []) if c is not None]
    except Exception as e:
        print("Bars hatasi:", kod, e)
        return []

def ema21_ustu(kod, close_f):
    closes = kapanislar(kod)
    if len(closes) < 22:
        return None
    ema = closes[0]
    for c in closes[1:]:
        ema = (c * 2 / 22) + (ema * 20 / 22)
    return close_f > ema

def kivilcim(kod):
    for host in ("query1", "query2"):
        for _ in range(3):
            try:
                url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{kod}.IS"
                r = requests.get(url, params={"range": "5d", "interval": "1d"}, headers=HEADERS, timeout=20)
                r.raise_for_status()
                q = r.json()["chart"]["result"][0]["indicators"]["quote"][0]
                for o, c in reversed(list(zip(q.get("open", []), q.get("close", [])))):
                    if o and c:
                        return (c - o) / o * 100
                return None
            except Exception as e:
                print("Kivilcim deneme:", kod, e)
    return None

def kap_basliklari():
    try:
        import re as _re
        r = requests.get("https://www.kap.org.tr/tr/rss", headers=HEADERS, timeout=20)
        r.raise_for_status()
        return _re.findall(r"<title>(.*?)</title>", r.text)
    except Exception as e:
        print("KAP rss hatasi:", e)
        return []

def tur():
    simdi = datetime.now(TRT)
    manuel = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if not manuel and simdi.weekday() >= 5:
        print("Hafta sonu, tur yok.")
        return
    state = oku(STATE, {})
    if not isinstance(state, dict):
        state = {}
    track = oku(TRACK, [])
    if not isinstance(track, list):
        track = []
    kap_bas = kap_basliklari()
    gonderilen = 0

    def sessiz_mi(kod):
        son = state.get(kod)
        if not son:
            return False
        try:
            return (simdi - datetime.fromisoformat(son)) < timedelta(hours=SESSIZLIK_SAAT)
        except Exception:
            return False

    def kap_var_mi(desc):
        if not kap_bas or not desc:
            return False
        kisa = desc[:12].upper()
        return any(kisa in t.upper() for t in kap_bas)

    # ---------- TABAN (UCUZ IZLEME) ----------
    data = tarama(
        ["description", "close", "change", "RSI", "volume", "relative_volume_10d_calc"],
        [
            {"left": "change", "operation": "greater", "right": -9.8},
            {"left": "change", "operation": "less", "right": -1.5},
            {"left": "RSI", "operation": "less", "right": 40},
            {"left": "relative_volume_10d_calc", "operation": "greater", "right": 1.3},
            {"left": "volume", "operation": "greater", "right": 100000},
        ],
    )
    for item in data:
        kod = (item.get("s") or "").strip()
        d = item.get("d") or []
        if not kod or len(d) < 6 or sessiz_mi(kod):
            continue
        desc, close, change, rsi, vol, rvol = d[0], d[1], d[2], d[3], d[4], d[5]
        try:
            close_f = float(close)
            vol_f = float(vol)
        except (TypeError, ValueError):
            continue
        if close_f * vol_f < 5000000:
            continue
        spark = kivilcim(kod)
        if spark is None:
            spark_txt = "Dönüş kıvılcımı şu an hesaplanamadı; sonraki turda yine bakacağım."
        elif spark > 0.5:
            spark_txt = f"🔥 Kıvılcım YANDI: açılışa göre {spark:+.1f}% — dönüş denemesi başladı."
        else:
            spark_txt = f"Kıvılcım henüz yok (açılışa göre {spark:+.1f}%); yeşil mum + hacim bekliyorum."
        haber_var = kap_var_mi(desc)
        haber_txt = "VAR → düşüşü açıklayan haber var" if haber_var else "YOK → düşüş habersiz (panik/sektör)"
        telegram_gonder(
            f"🔄 UCUZ İZLEME (taban dönüşü) — BIST:{kod}\n"
            f"🏢 {desc}\n"
            f"📉 Fiyat: {close_f:.2f} TL | RSI: {rsi:.0f} | Göreceli hacim: {rvol:.1f}x\n"
            f"💬 Özünde: Bugün {change:+.1f}% düştü, haber {'VAR' if haber_var else 'YOK'}; hacim {rvol:.1f}x. {spark_txt}\n"
            f"📰 KAP (24s): {haber_txt}\n"
            f"❓ Ne yapmalı: Şimdilik hiçbir şey. Kıvılcım yanarsa 🔥 mesajı göndereceğim; ancak o mesaj geldiğinde düşün.\n"
            f"📊 Deftere alındı: 48 saat sonra sonucu kendim raporlayacağım."
        )
        state[kod] = simdi.isoformat()
        track.append({"kod": kod, "fiyat": close_f, "ts": simdi.isoformat(), "done": False, "tip": "taban"})
        gonderilen += 1

    # ---------- TAVAN (MOMENTUM) ----------
    data = tarama(
        ["description", "close", "change", "RSI", "volume", "relative_volume_10d_calc", "ADX"],
        [
            {"left": "change", "operation": "greater", "right": 4.5},
            {"left": "change", "operation": "less", "right": 9.8},
            {"left": "RSI", "operation": "greater", "right": 55},
            {"left": "relative_volume_10d_calc", "operation": "greater", "right": 2},
            {"left": "volume", "operation": "greater", "right": 100000},
        ],
    )
    for item in data:
        kod = (item.get("s") or "").strip()
        d = item.get("d") or []
        if not kod or len(d) < 7 or sessiz_mi(kod):
            continue
        desc, close, change, rsi, vol, rvol, adx = d[0], d[1], d[2], d[3], d[4], d[5], d[6]
        try:
            close_f = float(close)
            vol_f = float(vol)
        except (TypeError, ValueError):
            continue
        if close_f * vol_f < 5000000:
            continue
        ust = ema21_ustu(kod, close_f)
        if ust is False:
            print("EMA21 altinda, elendi:", kod)
            continue
        ema_txt = "📐 EMA21: üstünde ✅\n" if ust else "📐 EMA21: veri yok (koşul atlandı)\n"
        adx_txt = f" | ADX: {adx:.0f}" if adx else ""
        haber_var = kap_var_mi(desc)
        haber_txt = "VAR → yükselişi açıklayan katalizör var" if haber_var else "YOK → habersiz momentum (spekülasyon riski yüksek)"
        telegram_gonder(
            f"🚀 TAVAN ADAYI — MOMENTUM\n"
            f"🏢 {desc} ({kod})\n"
            f"📈 {change:+.1f}% | Fiyat: {close_f:.2f} TL | RSI: {rsi:.0f} | Göreceli hacim: {rvol:.1f}x{adx_txt}\n"
            f"{ema_txt}"
            f"📰 KAP (24s): {haber_txt}\n"
            f"🎯 Strateji: trend + hacim onaylı momentum; tavan kilidi öncesi giriş denemesi; stop disiplini şart.\n"
            f"📊 Ölçüme alındı: 48s sonra sonuç raporu."
        )
        state[kod] = simdi.isoformat()
        track.append({"kod": kod, "fiyat": close_f, "ts": simdi.isoformat(), "done": False, "tip": "tavan"})
        gonderilen += 1

    # ---------- 48 SAAT SONUC ----------
    for t in track:
        if t.get("done"):
            continue
        ts_ham = t.get("ts") or t.get("tarih")
        try:
            ts = datetime.fromisoformat(ts_ham)
        except Exception:
            continue
        if (simdi - ts) < timedelta(hours=SONUC_SAAT):
            continue
        kod = t["kod"]
        p0 = t["fiyat"]
        closes = kapanislar(kod, "5d")
        if not closes:
            continue
        p1 = closes[-1]
        chg = (p1 - p0) / p0 * 100
        hukm = "kazandırdı 🎉" if chg > 1 else ("kaybettirdi 📉" if chg < -1 else "yerinde saydı 😐")
        telegram_gonder(
            f"📊 48-SAAT SONUCU — {kod} ({t.get('tip', '?')})\n"
            f"💬 Özünde: uyarı fiyatı {p0:.2f} → şimdi {p1:.2f} ({chg:+.1f}%). Hüküm: {hukm}.\n"
            f"📒 Deftere işlendi; karne hanesine yazıldı."
        )
        t["done"] = True

    yaz(STATE, state)
    yaz(TRACK, track)
    print("Tur bitti, gonderilen:", gonderilen)

tur()
