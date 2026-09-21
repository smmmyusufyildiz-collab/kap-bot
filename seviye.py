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

def olaylari_bul(w, p):
    olaylar = []
    stop = w.get("stop")
    if stop and p <= stop:
        olaylar.append(("stop", f"Fiyat ({p:.2f} TL) stop çizgisine ({stop:.2f} TL) indi veya altına geçti."))
    for sev in (w.get("destek"), w.get("destek2")):
        if not sev or p < sev * 0.5:
            continue
        if p < sev * 0.98:
            olaylar.append(("kirilmis", f"Fiyat ({p:.2f} TL) destek çizgisinin ({sev:.2f} TL) altına düştü: destek KIRILDI."))
        elif p <= sev * 1.01:
            olaylar.append(("test", f"Fiyat ({p:.2f} TL) destek çizgisine ({sev:.2f} TL) dayandı: kırılmadı, sadece dokunuyor."))
    direnc = w.get("direnç")
    if direnc:
        if p > direnc * 1.02:
            olaylar.append(("kirilmis", f"Fiyat ({p:.2f} TL) direnç çizgisinin ({direnc:.2f} TL) üstüne çıktı: direnç KIRILDI."))
        elif p >= direnc * 0.99:
            olaylar.append(("test", f"Fiyat ({p:.2f} TL) direnç çizgisine ({direnc:.2f} TL) dayandı: kırılmadı, sadece dokunuyor."))
    return olaylar

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
            for tip, aciklama in olaylari_bul(w, p):
                key = f"{kod}:{tip}"
                sessizlik = timedelta(hours=168) if tip == "kirilmis" else timedelta(hours=24)
                son = state.get(key)
                if son:
                    try:
                        if simdi - datetime.fromisoformat(son) < sessizlik:
                            continue
                    except Exception:
                        pass
                if tip == "stop":
                    yap = "Bu hisse sende varsa stop planını HEMEN gözden geçir; sende yoksa bu mesaj sadece bilgi."
                elif tip == "kirilmis":
                    yap = "Al-sat tavsiyesi değildir. Bu hisse sende varsa stop planını gözden geçir; yoksa tribünden izlemeye devam."
                else:
                    yap = "Şimdilik hiçbir şey: çizgi kırılmadı, sadece dokunuldu. Kırılır ya da sekerse yine yazarım."
                telegram_gonder(
                    f"🎯 SEVİYE NÖBETÇİSİ — {kod}\n"
                    f"💬 Özünde: {aciklama}\n"
                    f" {simdi.strftime('%H:%M')}\n"
                    f"❓ Ne yapmalı: {yap}\n"
                    f"📌 Grup seviyeleri: destek {w.get('destek', '-')} / direnç {w.get('direnç', '-')} / stop {w.get('stop', '-')}")
                state[key] = simdi.isoformat()
                degisti = True
                print("Seviye olayi:", kod, tip)

    dk = simdi.hour * 60 + simdi.minute
    if simdi.weekday() < 5 and (18 * 60 + 35) <= dk <= (19 * 60 + 5) and state.get("ozet_tarih") != simdi.date().isoformat():
        satirlar = ["🎯 İZLEME LİSTESİ — AKŞAM ÖZETİ", "💬 Özünde: her hisse çizgilerine göre nerede:"]
        for w in watch:
            p = son_fiyat(w.get("kod"))
            if not p:
                continue
            d, r = w.get("destek"), w.get("direnç")
            if d and p < d * 0.98:
                durum = "desteğin altında (kırılmış)"
            elif d and p <= d * 1.01:
                durum = "desteğe dayalı"
            elif r and p > r * 1.02:
                durum = "direncin üstünde (kırılmış)"
            elif r and p >= r * 0.99:
                durum = "dirence dayalı"
            else:
                durum = "çizgilerin arasında"
            satirlar.append(f"• {w['kod']}: {p:.2f} TL — {durum}")
        satirlar.append("❓ Ne yapmalı: Bu bir akşam özetidir, tavsiye değildir; gün içindeki kırılım/dokunma mesajları zaten gerekli uyarıları içerir.")
        telegram_gonder("\n".join(satirlar))
        state["ozet_tarih"] = simdi.date().isoformat()
        degisti = True
    if degisti:
        yaz(STATE_FILE, state)
    print("Seviye turu tamam")

tur()
