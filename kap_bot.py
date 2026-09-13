import os
import re
import json
import time
import requests

# ---------------- AYARLAR ----------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
GEMINI_KEY     = os.environ.get("GEMINI_API_KEY", "")

MIN_SCORE = 7
TAKIP     = []

STATE_FILE = "state.json"
KAP_URLS   = [
    "https://www.kap.org.tr/tr/api/disclosures",
    "https://www.kap.org.tr/api/disclosures",
]
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.kap.org.tr/tr/bildirim-sorgu",
    "Origin": "https://www.kap.org.tr",
}

# MUTLAKA YAKALANMASI GEREKEN KRITIK KELIMELER (AI'ya bakilmadan iletilir)
KRITIK_KELIMELER = [
    "halka arz", "halkaarz", "ipo",
    "bedelsiz", "bedelli", "sermaye artirimi", "sermaye artırımı",
    "temettu", "temettü", "kar payi", "kar payı",
    "birlesme", "birleşme", "devralma", "satinalma",
    "geri alim", "geri alım", "buyback"
]

# AI'ya ulasilamazsa diye ek guvenlik agi
ANAHTAR = ["ihale","sozlesme","sözleşme","yatirim","yatırım",
           "derecelendirme","rating","dava","ceza","anlasma","anlaşma",
           "ortaklik","ortaklık","fabrika","kapasite","lisans"]

# ---------------- YARDIMCILAR ----------------
def telegram_gonder(mesaj):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": mesaj, "disable_web_page_preview": True},
                      timeout=15)
    except Exception as e:
        print("Telegram hatasi:", e)

def kap_bildirim_cek():
    son_hata = None
    for url in KAP_URLS:
        for deneme in range(3):
            try:
                r = requests.get(url, headers=HEADERS, timeout=45)
                r.raise_for_status()
                veri = r.json()
                if isinstance(veri, dict):
                    for v in veri.values():
                        if isinstance(v, list) and v:
                            print("Kaynak calisiyor:", url)
                            return v
                    continue
                if isinstance(veri, list) and veri:
                    print("Kaynak calisiyor:", url)
                    return veri
            except Exception as e:
                son_hata = e
                print(f"Deneme basarisiz ({url}, deneme {deneme+1}): {e}")
                time.sleep(3)
    print("KAP baglanti hatasi (tum denemeler):", son_hata)
    return []

def alan(b, *anahtarlar):
    for k in anahtarlar:
        deger = b.get(k)
        if deger:
            return deger
    return "?"

def state_oku():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return int(json.load(f).get("son_indeks", 0))
    except Exception:
        return 0

def state_yaz(i):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"son_indeks": i}, f)

def derle(b):
    idx_s = alan(b, "disclosureIndex", "index", "id")
    idx = int(idx_s) if str(idx_s).lstrip("-").isdigit() else -1
    sirket = alan(b, "companyName", "companyTitle", "memberName", "company")
    baslik = alan(b, "title", "subject", "description", "disclosureSubject")
    tarih  = alan(b, "publishDate", "date", "time", "publishedAt")
    hisse  = str(alan(b, "stockCodes", "stockCode", "symbols"))
    icerik = alan(b, "content", "text", "body", "summary")
    return idx, sirket, baslik, tarih, hisse, icerik

def yapay_zeka_puanla(maddeler):
    liste = "\n".join(f"{i+1}. {s} | {b} | {t}" for i, (s, b, t) in enumerate(maddeler))
    prompt = (
        "Sen deneyimli bir Borsa Istanbul (BIST) analistisin.\n"
        "Asagidaki KAP bildirimlerini hisse degerine olasi etkisine gore 0-10 arasi puanla:\n"
        "0-3: rutin/idari (genel kurul gundemi, imza sirkuleri, rutin aciklamalar)\n"
        "4-6: orta onemli (bilgilendirme, kucuk capli islemler)\n"
        "7-10: onemli (yeni sozlesme/ihale, buyuk yatirim, temettu/bedelsiz karari, birlesme/devralma, "
        "hisse geri alim programi, onemli dava/ceza, reyting degisimi, onemli kar/zarar aciklamasi, "
        "HALKA ARZ sonuclari/yeni sirket girisi)\n"
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

def kritik_kelime_var(metin):
    kucuk = metin.lower()
    return any(k in kucuk for k in KRITIK_KELIMELER)

def anahtar_var(metin):
    kucuk = metin.lower()
    return any(k in kucuk for k in ANAHTAR)

# ---------------- ANA AKIS ----------------
bildirimler = kap_bildirim_cek()
if bildirimler:
    print("Ornek anahtarlar:", list(bildirimler[0].keys()))
    print(f"Toplam {len(bildirimler)} bildirim alindi")

son_indeks = state_oku()
manuel_test = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"

yeni = []
if bildirimler and son_indeks > 0:
    for b in bildirimler:
        idx, sirket, baslik, tarih, hisse, icerik = derle(b)
        if idx > son_indeks:
            if TAKIP and not any(t.upper() in hisse.upper() for t in TAKIP):
                continue
            yeni.append((idx, sirket, baslik, tarih, icerik))

# ILK CALISTIRMA: mevcutlari "gordum" say
if bildirimler and son_indeks == 0:
    indeksler = [derle(b)[0] for b in bildirimler]
    indeksler = [i for i in indeksler if i > 0]
    if indeksler:
        son_indeks = max(indeksler)
        state_yaz(son_indeks)
        print("Baslangic indeksi kaydedildi:", son_indeks)

# MANUEL TEST
if manuel_test:
    if bildirimler:
        son_uc = [derle(b)[1:4] for b in bildirimler[:3]]
        puanlar = yapay_zeka_puanla(son_uc) if GEMINI_KEY else None
        satirlar = ["🧪 AI analisti test raporu:"]
        if puanlar:
            for i, (s, ba, t) in enumerate(son_uc, start=1):
                p = next((x for x in puanlar if x.get("no") == i), None)
                if p:
                    satirlar.append(f"{i}) {s}\n   {ba}\n   → {p.get('puan','?')}/10 | {p.get('neden','')}")
        else:
            satirlar.append("AI'ya ulasilamadi (GEMINI_API_KEY secret'ini kontrol et).")
        satirlar.append(f"\nEsik: MIN_SCORE={MIN_SCORE} — sadece bu puan ve uzeri haberler iletilir.")
        satirlar.append("KRITIK_KELIMELER: halka arz, bedelsiz, temettu, birlesme, geri alim → otomatik iletilir.")
        telegram_gonder("\n".join(satirlar))
    else:
        telegram_gonder("🧪 Test: Telegram hatti calisiyor ✅\nKAP hatti bu turda yanit vermedi ❌")

# NORMAL AKIS
if yeni:
    puanlar = yapay_zeka_puanla([(s, b, t) for (_, s, b, t, _) in yeni]) if GEMINI_KEY else None
    gonderilen = 0
    for sira, (idx, sirket, baslik, tarih, icerik) in enumerate(yeni, start=1):
        puan, neden, onemli = None, "", False
        
        # KURAL 1: Kritik kelime varsa AI'ya bakma, direkt ilet
        if kritik_kelime_var(baslik + " " + icerik):
            onemli = True
            neden = "KRITIK kelime tespit edildi (halka arz/bedelsiz/temettu vb.)"
            puan = "⚡"
        
        # KURAL 2: AI puanlamasi
        elif puanlar:
            p = next((x for x in puanlar if x.get("no") == sira), None)
            if p:
                puan = p.get("puan")
                neden = p.get("neden", "")
                onemli = isinstance(puan, (int, float)) and puan >= MIN_SCORE
        
        # KURAL 3: AI yoksa anahtar kelime guvenlik agi
        else:
            onemli = anahtar_var(baslik + " " + icerik)
            neden = "AI'ya ulasilamadi; anahtar kelime filtresi yakaladi."
            puan = "-"
        
        if onemli:
            telegram_gonder(
                f"🚨 ÖNEMLİ KAP BİLDİRİMİ — Etki: {puan}/10\n"
                f"🏢 {sirket}\n📰 {baslik}\n🧠 {neden}\n🕐 {tarih}\n"
                f"🔗 https://www.kap.org.tr/tr/Bildirim/{idx}")
            gonderilen += 1
            print(f"Iletildi (puan {puan}): {sirket} - {baslik}")
    print(f"Bu turda {len(yeni)} yeni bildirim, {gonderilen} iletim.")
    son_indeks = max([son_indeks] + [i for (i, *_) in yeni])
    state_yaz(son_indeks)
else:
    print("Yeni bildirim yok.")
