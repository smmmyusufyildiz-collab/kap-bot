import os
import json
from datetime import datetime, timedelta, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))
TRACK = "taban_track.json"

def tg(mesaj):
    try:
        import requests
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

def tur():
    track = oku(TRACK, [])
    biten = [t for t in track if t.get("done") and t.get("sonuc_pct") is not None]
    if len(biten) < 3:
        tg(f"🔊 YANKI: henüz yeterli sonuç yok ({len(biten)} kapandı). 5 sonuç birikince ilk rapor gelecek.")
        return
    gruplar = {}
    for t in biten:
        if t.get("tip") == "taban":
            ana = "🔥 Kıvılcım yanmış taban" if t.get("kivilcim_yandi") else "❄️ Kıvılcım bekleyen taban"
        else:
            ana = "🚀 Tavan/momentum"
        gruplar.setdefault(ana, []).append(t["sonuc_pct"])
    satirlar = ["🔊 YANKI RAPORU — hangi sinyal türü çalışıyor?", ""]
    for ad, degerler in gruplar.items():
        n = len(degerler)
        kaz = sum(1 for x in degerler if x > 1)
        ort = sum(degerler) / n
        satirlar.append(f"{ad}\n• sinyal: {n} | kazanmış: {kaz} | ortalama: {ort:+.2f}%")
    saat_grup = {}
    for t in biten:
        try:
            h = datetime.fromisoformat(t.get("ts") or t.get("tarih")).hour
        except Exception:
            continue
        saat_grup.setdefault(h, []).append(t["sonuc_pct"])
    if saat_grup:
        en_iyi = max(saat_grup.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))
        satirlar.append(f"\n🕐 En verimli uyarı saati: {en_iyi[0]:02d}:00 (ortalama {sum(en_iyi[1]) / len(en_iyi[1]):+.2f}%)")
    satirlar.append("\n💬 Özünde: çok sinyal değil, ÇALIŞAN sinyal türü beslenir. Bu rapor Pazar akşamları otomatik gelir.")
    tg("\n".join(satirlar))

tur()
