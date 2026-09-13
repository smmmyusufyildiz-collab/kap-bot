import os
import re
import json
import hashlib
import requests
from bs4 import BeautifulSoup

# ---------------- AYARLAR ----------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
GEMINI_KEY     = os.environ.get("GEMINI_API_KEY", "")

MIN_SCORE = 7
TAKIP     = []

STATE_FILE = "state.json"
KAP_URL    = "https://www.kap.org.tr/tr/bildirim-sorgu-sonuc?srcbar=Y&cmp=Y&cat=4"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

# AI'ya bakilmadan OTOMATIK iletilen kritik kelimeler
KRITIK_KELIMELER = ["halka arz","halkaarz","ipo","bedelsiz","bedelli","sermaye artirimi","sermaye artırımı",
                    "temettu","temettü","kar payi","kar payı","birlesme","birleşme","devralma",
                    "geri alim","geri alım","ihale"]
ANAHTAR = ["sozlesme","sözleşme","yatirim","yatırım","derecelendirme","rating","dava","ceza",
           "anlasma","anlaşma","ortaklik","ortaklık","fabrika","kapasite","lisans"]

# ---------------- YARDIMCILAR ----------------
def telegram_gonder(mesaj):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": mesaj, "disable_web_page_preview": True},
                      timeout=15)
    except Exception as e:
        print("Telegram hatasi:", e)

def parmak_izi(metin):
    return hashlib.md5(metin.encode("utf-8")).hexdigest()

def kap_bildirim_cek():
    """KAP liste sayfasini tablo olarak okur; yeniden eskiye liste doner."""
    try:
        r = requests.get(KAP_URL, headers=HEADERS, timeout=60)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        sonuc = []
        for tr in soup.find_all("tr"):
            hucreler = [h.get_text(" ", strip=True) for h in tr.find_all(["td", "th"])]
            if len(hucreler) < 6:
                continue
            metin = " | ".join(hucreler)
            if not re.search(r"(Bugün|Dün|\d{2}\.\d{2}\.\d{4})", metin):
                continue
            if not re.search(r"\d{1,2}:\d{2}", metin):
                continue
            tm = re.search(r"(Bugün|Dün|\d{2}\.\d{2}\.\d{4})\s*\d{1,2}:\d{2}", metin)
            tarih = tm.group(0) if tm else "?"
            sirket = "?"
            for h in hucreler:
                m = re.search(r"(.{3,80}?A\.Ş\.)", h)
                if m:
                    sirket = m.group(1).strip()
                    break
            adaylar = [h for h in hucreler if len(h) > 15 and "A.Ş." not in h and not re.search(r"\d{1,2}:\d{2}", h)]
            baslik = max(adaylar, key=len) if adaylar else metin[:120]
            sonuc.append({"fp": parmak_izi(metin), "tarih": tarih,
                          "sirket": sirket, "baslik": baslik, "metin": metin})
        return sonuc
    except Exception as e:
        print("KAP baglanti hatasi:", e)
        return []

def state_oku():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def state_yaz(d):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f)

def yapay_zeka_puanla(maddeler):
    liste = "\n".join(f"{i+1}. {s} | {b} | {t}" for i, (s, b, t) in enumerate(maddeler))
    prompt = (
        "Sen deneyimli bir Borsa Istanbul (BIST) analistisin.\n"
        "Asagidaki KAP bildirimlerini hisse degerine olasi etkisine gore 0-10 arasi puanla:\n"
        "0-3: rutin/idari (genel kurul gundemi, imza sirkuleri, rutin aciklamalar)\n"
        "4-6: orta onemli (bilgilendirme, kucuk capli islemler)\n"
        "7-10: onemli (yeni sozlesme/ihale, buyuk yatirim, temettu/bedelsiz karari, birlesme/devralma, "
        "hisse geri alim programi, onemli dava/ceza, reyting degisimi, onemli kar/zarar, HALKA ARZ sonuclari)\n"
        "YALNIZCA su formatta JSON dizisi dondur, baska hicbir sey yazma:\n"
        '[{"no": 1, "puan": 8, "neden": "tek cumlelik gerekce"}]\n\n'
        "BILDIRIMLER:\n" + liste
    )
    try:
        r = requests.post(GEMINI_URL, params={"key": GEMINI_KEY},
                          json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=60)
        r.raise_for_status()
        metin = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        m = re.search(r"\[.*\]", metin, re.S)
        return json.loads(m.group(0)) if m else []
    except Exception as e:
        print("AI degerlendirme hatasi:", e)
        return None

def kritik_var(metin):
    k = metin.lower()
    return any(x in k for x in KRITIK_KELIMELER)

def anahtar_var(metin):
    k = metin.lower()
    return any(x in k for x in ANAHTAR)

# ---------------- ANA AKIS ----------------
bildirimler = kap_bildirim_cek()
print(f"KAP sayfasindan {len(bildirimler)} satir okundu")
if bildirimler:
    print("En yeni satir:", bildirimler[0]["sirket"], "-", bildirimler[0]["baslik"])

state = state_oku()
marker = state.get("marker", "")
manuel_test = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"

yeni = []
if bildirimler:
    if not marker:
        marker = bildirimler[0]["fp"]
        state_yaz({"marker": marker})
        print("Ilk calistirma: yer imi kondu, gecmis haberler atlanacak")
    else:
        for b in bildirimler:
            if b["fp"] == marker:
                break
            yeni.append(b)
        else:
            print("Yer imi bulunamadi (cok buyuk bosluk?), imi resetliyorum - spam onlemi")
            yeni = []
            marker = bildirimler[0]["fp"]
            state_yaz({"marker": marker})

# TAKIP filtresi
if TAKIP:
    yeni = [b for b in yeni if any(re.search(r"\b" + t + r"\b", b["metin"]) for t in TAKIP)]

# MANUEL TEST: son 3 gercek satiri puanlayip rapor gonder
if manuel_test and bildirimler:
    son_uc = [(b["sirket"], b["baslik"], b["tarih"]) for b in bildirimler[:3]]
    puanlar = yapay_zeka_puanla(son_uc) if GEMINI_KEY else None
    satirlar = ["🧪 AI analisti test raporu (gercek KAP satirlari):"]
    if puanlar:
        for i, (s, ba, t) in enumerate(son_uc, start=1):
            p = next((x for x in puanlar if x.get("no") == i), None)
            if p:
                satirlar.append(f"{i}) {s}\n   {ba}\n   → {p.get('puan','?')}/10 | {p.get('neden','')}")
    else:
        satirlar.append("AI'ya ulasilamadi (GEMINI_API_KEY kontrol).")
    satirlar.append(f"\nEsik: MIN_SCORE={MIN_SCORE}. Kritik kelimeler (halka arz, bedelsiz, temettu...) her zaman iletilir.")
    telegram_gonder("\n".join(satirlar))

# NORMAL AKIS
if yeni:
    print(f"{len(yeni)} yeni bildirim var")
    puanlar = yapay_zeka_puanla([(b["sirket"], b["baslik"], b["tarih"]) for b in yeni]) if GEMINI_KEY else None
    gonderilen = 0
    for sira, b in enumerate(yeni, start=1):
        puan, neden, onemli = None, "", False
        if kritik_var(b["metin"]):
            onemli, neden, puan = True, "KRITIK kelime (halka arz/bedelsiz/temettu vb.)", "⚡"
        elif puanlar:
            p = next((x for x in puanlar if x.get("no") == sira), None)
            if p:
                puan = p.get("puan")
                neden = p.get("neden", "")
                onemli = isinstance(puan, (int, float)) and puan >= MIN_SCORE
        else:
            onemli = anahtar_var(b["metin"])
            neden = "AI'ya ulasilamadi; anahtar kelime agi yakaladi."
            puan = "-"
        if onemli:
            telegram_gonder(
                f"🚨 ÖNEMLİ KAP BİLDİRİMİ — Etki: {puan}/10\n"
                f"🏢 {b['sirket']}\n📰 {b['baslik']}\n🧠 {neden}\n🕐 {b['tarih']}\n"
                f"🔗 https://www.kap.org.tr/tr/bildirim-sorgu")
            gonderilen += 1
            print(f"Iletildi (puan {puan}): {b['sirket']} - {b['baslik']}")
    print(f"{gonderilen} haber iletildi")
    if bildirimler:
        state_yaz({"marker": bildirimler[0]["fp"]})
else:
    print("Yeni bildirim yok.")
