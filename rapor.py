import os
import json
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")

def telegram_gonder(mesaj):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": mesaj, "disable_web_page_preview": True},
                      timeout=15)
    except Exception as e:
        print("Telegram hatasi:", e)

def oku(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def istatistik(liste):
    tam = [k for k in liste if k.get("fark") is not None]
    bek = len([k for k in liste if not k.get("done")])
    if not tam:
        return None, bek
    farklar = [k["fark"] for k in tam]
    hit = sum(1 for f in farklar if f > 0)
    ort = sum(farklar) / len(farklar)
    i_best = max(range(len(farklar)), key=lambda i: farklar[i])
    i_worst = min(range(len(farklar)), key=lambda i: farklar[i])
    return {
        "n": len(tam), "hit": hit, "oran": hit / len(tam) * 100, "ort": ort,
        "best": (tam[i_best].get("kod", "?"), farklar[i_best]),
        "worst": (tam[i_worst].get("kod", "?"), farklar[i_worst]),
    }, bek

def blok(ad, emoji, ist, bek):
    if ist is None:
        return f"{emoji} {ad}: henüz tamamlanmış örnek yok (bekleyen: {bek})"
    yorum = ""
    if ist["n"] >= 5:
        if ist["oran"] >= 60:
            yorum = "\n   💬 Güçlü sinyal ailesi — eşikler korunacak."
        elif ist["oran"] < 50:
            yorum = "\n   💬 Zayıf — Faz 2 bu ailenin eşiklerini sıkılaştıracak."
    return (f"{emoji} {ad}: {ist['n']} tamamlanmış (bekleyen: {bek})\n"
            f"   ✅ İsabet: %{ist['oran']:.0f} ({ist['hit']} yükseldi / {ist['n'] - ist['hit']} düştü)\n"
            f"   📊 Ort. 48s getiri: {ist['ort']:+.2f}%\n"
            f"   🏆 En iyi: {ist['best'][0]} {ist['best'][1]:+.1f}% | 💥 En kötü: {ist['worst'][0]} {ist['worst'][1]:+.1f}%{yorum}")

kap = oku("track.json")
rad = oku("radar_track.json")
tab = oku("taban_track.json")
ik, bk = istatistik(kap)
ir, br = istatistik(rad)
it, bt = istatistik(tab)

satirlar = ["🧠 HAFTALIK ÖZ-DEĞERLENDİRME RAPORU"]
satirlar.append(blok("KAP sinyalleri", "📚", ik, bk))
satirlar.append(blok("Radar sinyalleri", "📡", ir, br))

tum = [k for k in kap + rad if k.get("fark") is not None]
if tum:
    f = [k["fark"] for k in tum]
    hit = sum(1 for x in f if x > 0)
    satirlar.append(f"🧾 GENEL: {len(f)} örnek, %{hit / len(f) * 100:.0f} isabet, ort. {sum(f) / len(f):+.2f}%")
satirlar.append("📌 Sonraki rapor: Pazar 17:00. Faz 2, eşikleri bu karnelere göre kendi ayarlayacak.")
telegram_gonder("\n".join(satirlar))
print("Rapor gonderildi")
