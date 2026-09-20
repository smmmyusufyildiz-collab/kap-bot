import os
import re
import json
import requests
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))

SCANNER   = "https://scanner.tradingview.com/turkey/scan"
KAP_URL   = "https://www.kap.org.tr/tr/bildirim-sorgu-sonuc?srcbar=Y&cmp=Y&cat=4"
STATE     = "taban_state.json"
TRACK     = "taban_track.json"
SESSIZLIK_SAAT = 24

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}

def telegram_gonder(mesaj):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": mesaj, "disable_web_page_preview": True},
                      timeout=15)
    except Exception as e:
        print("Telegram hatasi:", e)

def seans_icinde_mi():
    s = datetime.now(TRT)
    if s.weekday() >= 5:
        return False
    dk = s.hour * 60 + s.minute
    return (9 * 60 + 45) <= dk <= (18 * 60 + 10)

def tarama_taban():
    body = {
        "columns": ["description", "close", "change", "RSI", "volume", "relative_volume_10d_calc"],
        "filter": [
            {"left": "change", "operation": "greater", "right": -9.9},
            {"left": "change", "operation": "less", "right": -2},
            {"left": "RSI", "operation": "greater", "right": 25},
            {"left": "RSI", "operation": "less", "right": 50},
            {"left": "relative_volume_10d_calc", "operation": "greater", "right": 1.5},
            {"left": "volume", "operation": "greater", "right": 50000},
        ],
        "sort": {"sortBy": "relative_volume_10d_calc", "sortOrder": "desc"},
        "range": [0, 15],
        "options": {"lang": "tr"},
    }
    r = requests.post(SCANNER, json=body, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])

def kivilcim(kod):
    """Gun icinde acilistan itibaren degisim %; pozitifse donus kivilcimi."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{kod}.IS"
        r = requests.get(url, params={"range": "1d", "interval": "5m"}, headers=HEADERS, timeout=20)
        r.raise_for_status()
        meta = r.json()["chart"]["result"][0]["meta"]
        acilis = meta.get("regularMarketOpen")
        fiyat = meta.get("regularMarketPrice")
        if acilis and fiyat:
            return (fiyat - acilis) / acilis * 100
    except Exception as e:
        print("Kivilcim hesabi hatasi:", kod, e)
    return None

def kap_son24_kodlar():
    kodlar = set()
    try:
        r = requests.get(KAP_URL, headers=HEADERS, timeout=60)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        simdi = datetime.now(TRT)
        for tr in soup.find_all("tr"):
            hucreler = [h.get_text(" ", strip=True) for h in tr.find_all(["td", "th"])]
            metin = " | ".join(hucreler)
            tm = re.search(r"(Bugün|Dün|\d{2}\.\d{2}\.\d{4})\s+(\d{1,2}):(\d{2})", metin)
            if not tm:
                continue
            if tm.group(1) == "Bugün":
                dt = simdi.replace(hour=int(tm.group(2)), minute=int(tm.group(3)))
            elif tm.group(1) == "Dün":
                dt = (simdi - timedelta(days=1)).replace(hour=int(tm.group(2)), minute=int(tm.group(3)))
            else:
                g, a, y = tm.group(1).split(".")
                dt = datetime(int(y), int(a), int(g), int(tm.group(2)), int(tm.group(3)), tzinfo=TRT)
            if simdi - dt > timedelta(hours=24):
                continue
            for hucre in hucreler:
                if re.fullmatch(r"[A-Z0-9]{3,6}(?: [A-Z0-9]{3,6})*(?: \(\+\d+\))?", hucre):
                    for tok in re.findall(r"[A-Z0-9]{3,6}", hucre):
                        kodlar.add(tok)
    except Exception as e:
        print("KAP capraz kontrol hatasi:", e)
    return kodlar

def son_kapanis(kod):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{kod}.IS"
        r = requests.get(url, params={"range": "5d", "interval": "1d"}, headers=HEADERS, timeout=30)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        closes = [c for c in res["indicators"]["quote"][0].get("close", []) if c is not None]
        return float(closes[-1]) if closes else None
    except Exception as e:
        print("Son kapanis hatasi:", kod, e)
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

def takip_kontrol():
    liste = oku(TRACK, [])
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
            continue
        baz = k["baz"]
        fark = (son - baz) / baz * 100
        emoji = "📈" if fark > 0 else ("📉" if fark < 0 else "➖")
        bas = "🔥 KIVILCIM" if k.get("tip") == "kivilcim" else "🔄 TABAN"
        telegram_gonder(
            f"📊 {bas} STRATEJİSİ 48-SAAT SONUCU\n"
            f"🏢 {k.get('desc', '')} ({k['kod']})\n"
            f"📉 Adayken: {k['degisim']:+.1f}% | baz {baz:.2f} TL\n"
            f"💰 48s kapanış: {son:.2f} TL\n"
            f"{emoji} Sonuç: {fark:+.2f}%\n"
            f"📒 Deftere işlendi: haftalık karnede kendi hanesine yazılacak.")
        k["son"] = son
        k["fark"] = round(fark, 2)
        k["done"] = True
        degisti = True
    if degisti:
        yaz(TRACK, liste)

def tur(manuel=False):
    simdi = datetime.now(TRT)
    takip_kontrol()
    if not manuel and not seans_icinde_mi():
        print("Seans disinda, taban radari uyuyor.")
        return
    try:
        adaylar = tarama_taban()
    except Exception as e:
        print("Scanner hatasi:", e)
        return
    if not adaylar:
        print("Eslesme yok.")
        return
    kap_kodlari = kap_son24_kodlar()
    state = oku(STATE, {})
    gonderilen = 0
    for item in adaylar:
        if gonderilen >= 5:
            break
        kod = (item.get("s") or "").strip()
        d = item.get("d", [])
        if not kod or len(d) < 6:
            continue
        son_u = state.get(kod)
        if son_u:
            try:
                if simdi - datetime.fromisoformat(son_u) < timedelta(hours=SESSIZLIK_SAAT):
                    continue
            except Exception:
                pass
        desc, close, change, rsi, vol, rvol = d[0], d[1], d[2], d[3], d[4], d[5]
        spark = kivilcim(kod)
        kiv = spark is not None and spark > 0
        tip = "kivilcim" if kiv else "taban"
        haber_var = kod in kap_kodlari
        haber_txt = "VAR → düşüşün bir haber nedeni olabilir" if haber_var else "YOK → düşüş habersiz (panik/sektör)"
        if kiv:
            baslik = "🔥 İLK KIVILCIM — TABANDAN DÖNÜŞTE İLK YEŞİL"
            kiv_satir = f"🌱 Açılıştan değişim: {spark:+.1f}% → gün içi dönüş tetiği YANDI\n"
        else:
            baslik = "🔄 TABAN DÖNÜŞ ADAYI"
            kiv_satir = f"🌱 Açılıştan değişim: {spark:+.1f}% → tetik henüz yok, havuzda izleniyor\n" if spark is not None else ""
        telegram_gonder(
            f"{baslik}\n"
            f"🏢 {desc} ({kod})\n"
            f"📉 {change:+.1f}% | Fiyat: {close} TL | RSI: {rsi:.0f} | Göreceli hacim: {rvol:.1f}x\n"
            f"{kiv_satir}"
            f"📰 KAP (24s): {haber_txt}\n"
            f"🎯 Strateji: RSI 25-50 + hacim ilgisi" + (" + açılıştan yeşil = onaylı giriş sinyali" if kiv else "; kıvılcım bekleniyor") + "; stop disiplini şart.\n"
            f"📊 Ölçüme alındı: 48s sonra sonuç raporu.")
        state[kod] = simdi.isoformat()
        gonderilen += 1
        lt = oku(TRACK, [])
        lt.append({"kod": kod, "desc": desc, "baz": float(close), "degisim": float(change),
                   "tip": tip,
                   "hedef_t": (simdi + timedelta(hours=48)).isoformat(), "done": False})
        yaz(TRACK, lt)
        print("Aday:", kod, "tip:", tip)
    yaz(STATE, state)
    if manuel and gonderilen == 0:
        telegram_gonder("🔄 TABAN RADARI TEST: şu an filtrelerine uyan aday yok (ekran boş).")
    print(f"{gonderilen} aday bildirildi")

tur(manuel=(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"))
