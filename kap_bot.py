import os
import re
import json
import requests

# ---------------- AYARLAR ----------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
GEMINI_KEY     = os.environ.get("GEMINI_API_KEY", "")

MIN_SCORE = 7      # 0-10: sadece bu puan ve uzeri haberler gelir (6=daha cok, 8=sadece cok onemli)
TAKIP     = []     # orn. ["THYAO","ASELS"]; bos = tum hisseler

STATE_FILE = "state.json"
KAP_URL    = "https://www.kap.org.tr/tr/api/disclosures"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# AI'ya ulasilamazsa diye guvenlik agi (anahtar kelimeler)
ANAHTAR = ["ihale","sozlesme","sözleşme","yatirim","yatırım","temettu","temettü","bedelsiz","bedelli",
           "geri alim","geri alım","birlesme","birleşme","devralma","kar payi","kar payı","derecelendirme",
           "rating","dava","ceza","anlasma","anlaşma","ortaklik","ortaklık","fabrika","kapasite","lisans"]

# ---------------- YARDIMCILAR ----------------
def telegram_gonder(mesaj):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": mesaj, "disable_web_page_preview": True},
                      timeout=15)
    except Exception as e:
        print("Telegram hatasi:", e)

def kap_bildirim_cek():
    try:
        r = requests.get(KAP_URL, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=20)
        r.raise_for_status()
        veri = r.json()
        if isinstance(veri, dict):
            for v in veri.values():
                if isinstance(v, list):
                    return v
            return []
        return veri if isinstance(veri, list) else []
    except Exception as e:
        print("KAP baglanti hatasi:", e)
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
    return idx, sirket, baslik, tarih, hisse

def yapay_zeka_puanla(maddeler):
    liste = "\n".join(f"{i+1}. {s} | {b} | {t}" for i, (s, b, t) in enumerate(maddeler))
    prompt = (
        "Sen deneyimli bir Borsa Istanbul (BIST) analistisin.\n"
        "Asagidaki KAP bildirimlerini hisse degerine olasi etkisine gore 0-10 arasi puanla:\n"
        "0-3: rutin/idari (genel kurul gundemi, imza sirkuleri, rutin aciklamalar)\n"
        "4-6: orta onemli (bilgilendirme, kucuk capli islemler)\n"
        "7-10: onemli (yeni sozlesme/ihale, buyuk yatirim, temettu/bedelsiz karari, birlesme/devralma, "
        "hisse geri alim programi, onemli dava/ceza, reyting degisimi, onemli kar/zarar aciklamasi)\n"
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

def anahtar_var(metin):
    kucuk = metin.lower()
    return any(k in kucuk for k in ANAHTAR)

# ---------------- ANA AKIS ----------------
bildirimler = kap_bildirim_cek()
if bildirimler:
    print("Ornek anahtarlar:", list(bildirimler[0].keys()))

son_indeks = state_oku()
manuel_test = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"

yeni = []
if bildirimler and son_indeks > 0:
    for b in bildirimler:
        idx, sirket, baslik, tarih, hisse = derle(b)
        if idx > son_indeks:
            if TAKIP and not any(t.upper() in hisse.upper() for t in TAKIP):
                continue
            yeni.append((idx, sirket, baslik, tarih))

# ILK CALISTIRMA: mevcutlari "gordum" say
if bildirimler and son_indeks == 0:
    indeksler = [derle(b)[0] for b in bildirimler]
    indeksler = [i for i in indeksler if i > 0]
    if indeksler:
        son_indeks = max(indeksler)
        state_yaz(son_indeks)
        print("Baslangic indeksi kaydedildi:", son_indeks)

# MANUEL TEST: son 3 bildirimi puanlayip demo rapor gonder
if manuel_test and bildirimler:
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
    telegram_gonder("\n".join(satirlar))

# NORMAL AKIS: yeni bildirimleri puanla, onemlileri gonder
if yeni:
    puanlar = yapay_zeka_puanla([(s, b, t) for (_, s, b, t) in yeni]) if GEMINI_KEY else None
    gonderilen = 0
    for sira, (idx, sirket, baslik, tarih) in enumerate(yeni, start=1):
        puan, neden, onemli = None, "", False
        if puanlar:
            p = next((x for x in puanlar if x.get("no") == sira), None)
            if p:
                puan = p.get("puan")
                neden = p.get("neden", "")
                onemli = isinstance(puan, (int, float)) and puan >= MIN_SCORE
        else:
            onemli = anahtar_var(baslik)
            neden = "AI'ya ulasilamadi; anahtar kelime filtresi yakaladi."
            puan = "-"
        if onemli:
            telegram_gonder(
                f"🚨 ÖNEMLİ KAP BİLDİRİMİ — Etki: {puan}/10\n"
                f"🏢 {sirket}\n📰 {baslik}\n🧠 {neden}\n🕐 {tarih}\n"
                f"🔗 https://www.kap.org.tr/tr/Bildirim/{idx}")
            gonderilen += 1
            print("Iletildi (puan", puan, "):", sirket, "-", baslik)
    print(f"Bu turda {len(yeni)} yeni bildirim, {gonderilen} iletim.")
    son_indeks = max([son_indeks] + [i for (i, *_) in yeni])
    state_yaz(son_indeks)
else:
    print("Yeni bildirim yok.")
