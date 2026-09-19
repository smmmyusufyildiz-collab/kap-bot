import os
import re
import json
import time
import hashlib
import requests
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

# ---------------- AYARLAR ----------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
GEMINI_KEY     = os.environ.get("GEMINI_API_KEY", "")

MIN_SCORE = 7
TAKIP     = []

STATE_FILE = "state.json"
TRACK_FILE = "track.json"
KAP_URL    = "https://www.kap.org.tr/tr/bildirim-sorgu-sonuc?srcbar=Y&cmp=Y&cat=4"
AI_HATA = ""
TRT = timezone(timedelta(hours=3))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

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

def temizle(hata):
    s = re.sub(r"key=[A-Za-z0-9_\.\-]+", "key=***", str(hata))
    s = re.sub(r"https?://\S+", "<url>", s)
    return s

def parmak_izi(metin):
    return hashlib.md5(metin.encode("utf-8")).hexdigest()

def tarih_cozun(s):
    m = re.search(r"(Bugün|Dün|(\d{2})\.(\d{2})\.(\d{4}))\s+(\d{1,2}):(\d{2})", s)
    if not m:
        return None
    simdi = datetime.now(TRT)
    if m.group(1) == "Bugün":
        d = simdi.date()
    elif m.group(1) == "Dün":
        d = simdi.date() - timedelta(days=1)
    else:
        d = datetime(int(m.group(4)), int(m.group(3)), int(m.group(2))).date()
    return datetime(d.year, d.month, d.day, int(m.group(5)), int(m.group(6)), tzinfo=TRT)

def seans_etiketi(dt):
    if dt.weekday() >= 5:
        return "SEANS DIŞI"
    if dt.hour < 10:
        return "SEANS ÖNCESİ"
    if dt.hour < 18:
        return "SEANS İÇİ"
    return "SEANS DIŞI"

def kod_bul(b, p):
    kod = str((p or {}).get("kod", "")).strip().upper()
    if kod and kod in b["metin"].upper():
        return kod
    return ""

def mesaj_kur(b, p, baz=None):
    dt = tarih_cozun(b["tarih"])
    simdi = datetime.now(TRT)
    dk = int((simdi - dt).total_seconds() // 60) if dt else "?"
    if dk == 0:
        dk = "00"
    seans = seans_etiketi(dt) if dt else "?"
    kod = kod_bul(b, p)
    ust = f"{kod} – {b['tarih']} – {seans} – {b['baslik']}" if kod else f"{b['tarih']} – {seans} – {b['baslik']}"
    msg = (
        f"⏱ KAP {dk} Dakika\n"
        f"🏢 {b['sirket']}\n"
        f"📰 {ust}\n\n"
        f"📝 {p.get('ozet', '')}\n\n"
        f"💡 Neden önemli: {p.get('neden', '')}\n"
        f"📈 Olası etki: {p.get('etki', '')}\n"
        f"⚠️ En önemli risk/karşı argüman: {p.get('risk', '')}\n"
        f"🧠 AI etki puanı: {p.get('puan', '?')}/10\n"
    )
    if baz:
        msg += f"📊 Takip başladı: baz kapanış {baz:.2f} TL — 48s sonra değişimi bildireceğim.\n"
    msg += "🔗 Doğrudan KAP bildirimi: https://www.kap.org.tr/tr/bildirim-sorgu"
    return msg

# ---------------- FİYAT KAYNAĞI (Yahoo Finance) ----------------
def yahoo_bars(kod):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{kod}.IS"
    r = requests.get(url, params={"range": "1mo", "interval": "1d"},
                     headers={"User-Agent": HEADERS["User-Agent"]}, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res.get("timestamp", [])
    closes = res["indicators"]["quote"][0].get("close", [])
    bars = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        bars.append((datetime.fromtimestamp(t, TRT), float(c)))
    return bars

def baz_kapanis(kod, dt_haber):
    """Haber anindan onceki son gunluk kapanis."""
    try:
        secili = None
        for dt, c in yahoo_bars(kod):
            if dt.date() < dt_haber.date() or (dt.date() == dt_haber.date() and dt_haber.hour >= 18):
                secili = c
        return secili
    except Exception as e:
        print("Baz kapanis alinamadi:", kod, temizle(e))
        return None

def son_kapanis(kod):
    try:
        bars = yahoo_bars(kod)
        return bars[-1][1] if bars else None
    except Exception as e:
        print("Son kapanis alinamadi:", kod, temizle(e))
        return None

# ---------------- TAKİP DEFTERİ ----------------
def track_oku():
    try:
        with open(TRACK_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def track_yaz(l):
    with open(TRACK_FILE, "w", encoding="utf-8") as f:
        json.dump(l, f, ensure_ascii=False)

def takipleri_kontrol_et():
    liste = track_oku()
    if not liste:
        return
    simdi = datetime.now(TRT)
    degisti = False
    for k in liste:
        if k.get("done"):
            continue
        try:
            hedef = datetime.fromisoformat(k["hedef_t"])
        except Exception:
            k["done"] = True
            degisti = True
            continue
        if simdi < hedef:
            continue
        son = son_kapanis(k["kod"])
        if son is None:
            if simdi > hedef + timedelta(days=5):
                k["done"] = True
                degisti = True
                telegram_gonder(f"📊 48-saat takibi: {k['kod']} için fiyat verisi alınamadı, takip kapatıldı.")
            continue
        baz = k["baz"]
        fark = (son - baz) / baz * 100
        emoji = "📈" if fark > 0 else ("📉" if fark < 0 else "➖")
        telegram_gonder(
            f"📊 48-SAAT TAKİP RAPORU\n"
            f"🏢 {k['kod']}\n"
            f"📰 Haber: {k['baslik'][:80]}\n"
            f"💰 Baz kapanış: {baz:.2f} TL\n"
            f"💰 48s kapanış: {son:.2f} TL\n"
            f"{emoji} Değişim: {fark:+.2f}%")
        k["son"] = son
        k["fark"] = round(fark, 2)
        k["done"] = True
        degisti = True
        print("Takip raporu gönderildi:", k["kod"], f"{fark:+.2f}%")
    if degisti:
        track_yaz(liste)

# ---------------- KAP OKUYUCU ----------------
def kap_bildirim_cek():
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
            sonuc.append({"fp": parmak_izi(tarih + "|" + sirket + "|" + baslik),
                          "tarih": tarih, "sirket": sirket, "baslik": baslik, "metin": metin})
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

# ---------------- MODEL AVCISI + AI ----------------
def gemini_modelleri():
    for base in ("v1beta", "v1"):
        try:
            r = requests.get(f"https://generativelanguage.googleapis.com/{base}/models",
                             headers={"x-goog-api-key": GEMINI_KEY}, timeout=30)
            if r.status_code == 200:
                adlar = [m.get("name", "") for m in r.json().get("models", [])]
                print(f"{base}: {len(adlar)} model bulundu")
                return base, adlar
            print(f"Model listesi {base}: {r.status_code}")
        except Exception as e:
            print("Model listesi hatasi:", temizle(e))
    return None, []

def model_sec(adlar):
    for tercih in ("gemini-3-flash", "gemini-flash-latest", "gemini-2.5-flash", "flash"):
        for a in adlar:
            if tercih in a and not any(x in a for x in ("image", "tts", "embedding", "audio")):
                return a.split("/")[-1]
    return None

def yapay_zeka_puanla(maddeler):
    global AI_HATA
    if not GEMINI_KEY:
        AI_HATA = "GEMINI_API_KEY bos"
        return None
    liste = "\n".join(f"{i+1}. {s} | {b} | {t}" for i, (s, b, t) in enumerate(maddeler))
    prompt = (
        "Sen deneyimli bir Borsa Istanbul (BIST) analistisin.\n"
        "Asagidaki KAP bildirimlerini degerlendir. Her biri icin:\n"
        "- puan: hisse degerine olasi etki 0-10 (0-3 rutin, 4-6 orta, 7-10 onemli)\n"
        "- kod: sirketin BIST hisse kodu (emin degilsen bos birak)\n"
        "- ozet: bildirimin 1-2 cumlelik ozu\n"
        "- neden: neden onemli, 1 cumle\n"
        "- etki: kisa vade olasi fiyat/algı etkisi, 1 cumle\n"
        "- risk: en onemli risk/karsi arguman, 1 cumle\n"
        "YALNIZCA su formatta JSON dizisi dondur:\n"
        '[{"no":1,"puan":8,"kod":"TTKOM","ozet":"...","neden":"...","etki":"...","risk":"..."}]\n\n'
        "BILDIRIMLER:\n" + liste
    )
    hatalar = []
    base, adlar = gemini_modelleri()
    modeller = []
    secili = model_sec(adlar)
    if secili:
        modeller.append(secili)
    for y in ("gemini-flash-latest", "gemini-3-flash", "gemini-2.5-flash"):
        if y not in modeller:
            modeller.append(y)
    base = base or "v1beta"

    for model in modeller[:4]:
        url = f"https://generativelanguage.googleapis.com/{base}/models/{model}:generateContent"
        for deneme in range(2):
            try:
                r = requests.post(url, headers={"x-goog-api-key": GEMINI_KEY},
                                  json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=60)
                if r.status_code in (429, 500, 503):
                    hatalar.append(f"{model}:{r.status_code}")
                    time.sleep(4)
                    continue
                if r.status_code == 404:
                    hatalar.append(f"{model}:404")
                    break
                r.raise_for_status()
                metin = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                m = re.search(r"\[.*\]", metin, re.S)
                AI_HATA = ""
                print("AI calisti, model:", model)
                return json.loads(m.group(0)) if m else []
            except Exception as e:
                hatalar.append(f"{model}:{temizle(e)}")
                time.sleep(3)

    try:
        r = requests.post(f"https://generativelanguage.googleapis.com/{base}/openai/chat/completions",
                          headers={"Authorization": f"Bearer {GEMINI_KEY}"},
                          json={"model": modeller[0], "messages": [{"role": "user", "content": prompt}]},
                          timeout=60)
        r.raise_for_status()
        metin = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\[.*\]", metin, re.S)
        AI_HATA = ""
        print("AI openai-uyumlu uc noktadan calisti")
        return json.loads(m.group(0)) if m else []
    except Exception as e:
        hatalar.append("openai-uyumlu:" + temizle(e))

    AI_HATA = " | ".join(hatalar)[:300]
    print("AI hatalari:", AI_HATA)
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
sent = set(state.get("sent", []))
manuel_test = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"

yeni = []
if bildirimler:
    if not marker:
        marker = bildirimler[0]["fp"]
        state_yaz({"marker": marker, "sent": list(sent)})
        print("Ilk calistirma: yer imi kondu")
    else:
        for b in bildirimler:
            if b["fp"] == marker:
                break
            yeni.append(b)
        else:
            print("Yer imi bulunamadi, resetlendi (spam onlemi)")
            yeni = []
            marker = bildirimler[0]["fp"]
            state_yaz({"marker": marker, "sent": list(sent)})

if TAKIP:
    yeni = [b for b in yeni if any(re.search(r"\b" + t + r"\b", b["metin"]) for t in TAKIP)]

# MANUEL TEST
if manuel_test and bildirimler:
    son_uc = [(b["sirket"], b["baslik"], b["tarih"]) for b in bildirimler[:3]]
    puanlar = yapay_zeka_puanla(son_uc)
    satirlar = ["🧪 AI analisti test raporu (gercek KAP satirlari):"]
    if puanlar:
        for i, (s, ba, t) in enumerate(son_uc, start=1):
            p = next((x for x in puanlar if x.get("no") == i), None)
            if p:
                satirlar.append(f"{i}) {s}\n   {ba}\n   → {p.get('puan','?')}/10 | {p.get('neden','')}")
    else:
        satirlar.append(f"AI'ya ulasilamadi. SEBEP: {AI_HATA}")
    satirlar.append(f"\nEsik: MIN_SCORE={MIN_SCORE}. Kritik kelimeler her zaman iletilir.")
    telegram_gonder("\n".join(satirlar))
    if puanlar:
        p0 = next((x for x in puanlar if x.get("no") == 1), puanlar[0])
        telegram_gonder("🎬 FORMAT ÖNİZLEME (gercek satirdan):\n" + mesaj_kur(bildirimler[0], p0))

# 48 SAAT TAKİPLERİNİN KONTROLÜ (her turda)
takipleri_kontrol_et()

# NORMAL AKIS
if yeni:
    print(f"{len(yeni)} yeni bildirim var")
    puanlar = yapay_zeka_puanla([(b["sirket"], b["baslik"], b["tarih"]) for b in yeni])
    gonderilen = 0
    for sira, b in enumerate(yeni, start=1):
        if b["fp"] in sent:
            continue
        gonderilecek = False
        p = None
        if kritik_var(b["metin"]):
            p = next((x for x in (puanlar or []) if x.get("no") == sira), None) or {}
            gonderilecek = True
        elif puanlar:
            aday = next((x for x in puanlar if x.get("no") == sira), None)
            try:
                puan_f = float(aday.get("puan")) if aday else None
            except (TypeError, ValueError):
                puan_f = None
            if puan_f is not None and puan_f >= MIN_SCORE:
                p = aday
                gonderilecek = True
        elif anahtar_var(b["metin"]):
            gonderilecek = True
        if not gonderilecek:
            continue

        kod = kod_bul(b, p)
        dt = tarih_cozun(b["tarih"])
        baz = baz_kapanis(kod, dt) if (kod and dt) else None

        if p:
            telegram_gonder(mesaj_kur(b, p, baz))
        else:
            ek = f"\n📊 Takip başladı: baz kapanış {baz:.2f} TL — 48s sonra bildireceğim." if baz else ""
            telegram_gonder(
                f"⚡ ÖNEMLİ KAP BİLDİRİMİ (kritik kelime)\n"
                f"🏢 {b['sirket']}\n📰 {b['baslik']}\n🕐 {b['tarih']}{ek}\n"
                f"🔗 https://www.kap.org.tr/tr/bildirim-sorgu")
        gonderilen += 1
        sent.add(b["fp"])
        print("Iletildi:", b["sirket"], "-", b["baslik"])

        if kod and dt and baz:
            liste = track_oku()
            liste.append({"kod": kod, "baz": baz,
                          "hedef_t": (dt + timedelta(hours=48)).isoformat(),
                          "baslik": b["baslik"], "done": False})
            track_yaz(liste)
            print("Takip defterine eklendi:", kod, "baz:", f"{baz:.2f}")
    print(f"{gonderilen} haber iletildi")
    if bildirimler:
        state_yaz({"marker": bildirimler[0]["fp"], "sent": list(sent)[-200:]})
else:
    print("Yeni bildirim yok.")
