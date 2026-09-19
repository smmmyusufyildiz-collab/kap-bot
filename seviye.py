import os
import json
import requests
from datetime import datetime, timedelta, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))

WATCH_FILE = "watch.json"
STATE_FILE = "seviye_state.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}

def telegram_gonder(mesaj):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": mesaj, "disable_web_page_preview": True},
                      timeout=15)
    except Exception as e:
        print("Telegram hatasi:", e)

def son_fiyat(kod):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{kod}.IS"
        r = requests.get(url, params={"range": "1d", "interval": "5m"}, headers=HEADERS, timeout=20)
        r.raise_for_status()
        meta = r.json()["chart"]["result"][0]["meta"]
        return float(meta.get("regularMarketPrice"))
    except Exception as e:
        print("Fiyat hatasi:", kod, e)
        return None

def oku(path, bos=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return [] if bos is None else bos

def yaz(path, veri):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False)

def seviye_kontrol(kod, tip, seviye, p, esik_alt, esik_ust, emoji_baslik):
    """Seviye test/kirilim olayi uretir."""
    if seviye is None:
        return None
    oran = p / seviye
    if oran < esik_alt:
        return ("kirilmis", f"{emoji_baslik[1]} Seviye KIRILDI: {p:.2f} TL < {seviye:.2f} TL")
    if oran <= esik_ust:
        return ("test", f"{emoji_baslik[0]} Seviye TEST: {p:.2f} TL ≈ {seviye:.2f} TL (uzaklık %{(oran - 1) * 100:+.1f})")
    return None

def tur():
    simdi = datetime.now(TRT)
    watch = oku(WATCH_FILE, [])
    state = oku(STATE_FILE, {})
    if not watch:
        print("watch.json bos")
        return
    seans = simdi.weekday() < 5 and (9 * 60 + 40) <= simdi.hour * 60 + simdi.minute <= (18 * 60 + 30)
    degisti = False

    if seans:
        for w in watch:
            kod = w.get("kod")
            p = son_fiyat(kod)
            if not p:
                continue
            olaylar = []
            if w.get("stop"):
                if p <= w["stop"]:
                    olaylar.append(("stop", f"🛑 STOP SEVİYESİ: {p:.2f} TL ≤ {w['stop']:.2f} TL"))
            for anahtar, emoji in (("destek", ("🛡", "")), ("destek2", ("🛡", "")), ("direnç", ("🚧", ""))):
                sev = w.get(anahtar)
                if anahtar == "direnç":
                    sonuc = seviye_kontrol(kod, anahtar, sev, p, 0.98, 1.01, emoji) if sev else None
                    if sonuc and sonuc[0] == "kirilmis" and p > sev * 1.02:
                        sonuc = ("kirilmis", f"🚀 Direnç KIRILDI: {p:.2f} TL > {sev:.2f} TL")
                    elif sonuc and sonuc[0] == "kirilmis":
                        sonuc = None
                else:
                    sonuc = seviye_kontrol(kod, anahtar, sev, p, 0.98, 1.01, emoji) if sev else None
                if sonuc:
                    olaylar.append(sonuc)
            for tip, mesaj in olaylar:
                key = f"{kod}:{tip}"
                son = state.get(key)
                if son:
                    try:
                        if simdi - datetime.fromisoformat(son) < timedelta(hours=24):
                            continue
                    except Exception:
                        pass
                telegram_gonder(
                    f"🎯 İZLEME LİSTESİ — {kod}\n{mesaj}\n"
                    f"🕐 {simdi.strftime('%H:%M')}\n"
                    f"📌 Grup seviyeleri: destek {w.get('destek', '-')} / direnç {w.get('direnç', '-')} / stop {w.get('stop', '-')}\n"
                    f"🔎 Seviyeler referanstır, yatırım tavsiyesi değildir.")
                state[key] = simdi.isoformat()
                degisti = True
                print("Seviye olayi:", kod, tip)

    # Gunluk ozet: is gunu 18:35-19:05 arasi bir kez
    dk = simdi.hour * 60 + simdi.minute
    if simdi.weekday() < 5 and (18 * 60 + 35) <= dk <= (19 * 60 + 5) and state.get("ozet_tarih") != simdi.date().isoformat():
        satirlar = ["🎯 İZLEME LİSTESİ — GÜNLÜK ÖZET"]
        for w in watch:
            p = son_fiyat(w.get("kod"))
            if not p:
                continue
            sat = f"• {w['kod']}: {p:.2f} TL"
            if w.get("destek"):
                sat += f" | desteğe %{(p / w['destek'] - 1) * 100:+.1f}"
            if w.get("direnç"):
                sat += f" | dirence %{(p / w['direnç'] - 1) * 100:+.1f}"
            satirlar.append(sat)
        telegram_gonder("\n".join(satirlar))
        state["ozet_tarih"] = simdi.date().isoformat()
        degisti = True
    if degisti:
        yaz(STATE_FILE, state)
    print("Seviye turu tamam")

tur()
