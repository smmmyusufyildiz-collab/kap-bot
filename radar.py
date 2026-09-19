import os
import re
import json
import requests
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))

SCANNER     = "https://scanner.tradingview.com/turkey/scan"
KAP_URL     = "https://www.kap.org.tr/tr/bildirim-sorgu-sonuc?srcbar=Y&cmp=Y&cat=4"
RADAR_FILE  = "radar.json"
RADAR_TRACK = "radar_track.json"

ESIK_YUZDE = 3.0
ESIK_HACIM = 2.0
SESSIZLIK_SAAT = 6
MAKS_UYARI = 5

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
    return (9 * 60 + 40) <= dk <= (18 * 60 + 30)

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

def tarama(yon):
    op = "egreater" if yon == "up" else "eless"
    sag = ESIK_YUZDE if yon == "up" else -ESIK_YUZDE
    body = {
        "columns": ["description", "close", "change", "volume", "average_volume_10d_calc", "average_volume"],
        "filter": [{"left": "change", "operation": op, "right": sag}],
        "sort": {"sortBy": "change", "sortOrder": "desc" if yon == "up" else "asc"},
        "range": [0, 25],
        "options": {"lang": "tr"},
    }
    r = requests.post(SCANNER, json=body, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])

def kap_son24_kodlar(saat=24):
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
            if simdi - dt > timedelta(hours=saat):
                continue
            for hucre in hucreler:
                if re.fullmatch(r"[A-Z0-9]{3,6}(?: [A-Z0-9]{3,6})*(?: \(\+\d+\))?", hucre):
                    for tok in re.findall(r"[A-Z0-9]{3,6}", hucre):
                        kodlar.add(tok)
    except Exception as e:
        print("KAP capraz kontrol hatasi:", e)
    return kodlar

def state_oku():
    try:
        with open(RADAR_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"alerts": {}}

def state_yaz(d):
    with open(RADAR_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)

def radar_track_oku():
    try:
        with open(RADAR_TRACK, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def radar_track_yaz(l):
    with open(RADAR_TRACK, "w", encoding="utf-8") as f:
        json.dump(l, f, ensure_ascii=False)

def radar_takip_kontrol():
    """Radar uyarilarinin 48 saat sonucunu olcer ve deftere yazar."""
    liste = radar_track_oku()
    if not liste:
        return
    simdi = datetime.now(TRT)
    degisti = False
    kap_kodlari = None
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
        if kap_kodlari is None:
            kap_kodlari = kap_son24_kodlar(saat=48)
        haber = "EVET — hareketi haber doğruladı" if k["kod"] in kap_kodlari else "HAYIR — hareket habersiz kaldı"
        emoji = "📈" if fark > 0 else ("📉" if fark < 0 else "➖")
        telegram_gonder(
            f"📊 RADAR 48-SAAT SONUCU\n"
            f"🏢 {k.get('desc', '')} ({k['kod']})\n"
            f"💰 Uyarı kapanışı: {baz:.2f} TL → 48s: {son:.2f} TL\n"
            f"{emoji} Değişim: {fark:+.2f}%\n"
            f"📰 Arada KAP haberi düştü mü? {haber}")
        k["son"] = son
        k["fark"] = round(fark, 2)
        k["done"] = True
        degisti = True
        print("Radar sonucu gönderildi:", k["kod"], f"{fark:+.2f}%")
    if degisti:
        radar_track_yaz(liste)

def radar_tur(manuel=False):
    simdi = datetime.now(TRT)
    radar_takip_kontrol()   # 48s sonucları her turda kontrol edilir (hafta sonu dahil)
    if not manuel and not seans_icinde_mi():
        print("Seans disinda, radar uyuyor.")
        return
    try:
        yukan = tarama("up")
        asagi = tarama("down")
    except Exception as e:
        print("Scanner hatasi:", e)
        return
    kap_kodlari = kap_son24_kodlar()
    print(f"KAP son 24h kod sayisi: {len(kap_kodlari)}")
    state = state_oku()
    alerts = state.get("alerts", {})
    gonderilen = 0

    for item in (yukan + asagi):
        if gonderilen >= MAKS_UYARI:
            break
        kod = (item.get("s") or "").strip()
        d = item.get("d", [])
        if not kod or len(d) < 4:
            continue
        son_u = alerts.get(kod)
        if son_u:
            try:
                if simdi - datetime.fromisoformat(son_u) < timedelta(hours=SESSIZLIK_SAAT):
                    continue
            except Exception:
                pass
        desc, close, change, vol = d[0], d[1], d[2], d[3]
        avg10 = d[4] if len(d) > 4 else None
        avg = d[5] if len(d) > 5 else None
        try:
            change = float(change)
        except (TypeError, ValueError):
            continue
        oran = None
        try:
            baz = avg10 or avg
            if baz and vol:
                oran = float(vol) / float(baz)
        except (TypeError, ValueError, ZeroDivisionError):
            oran = None
        if oran is not None and oran < ESIK_HACIM and abs(change) < 5:
            continue
        if kod in kap_kodlari:
            print(f"{kod}: hareket haber kaynakli, atlandi")
            continue
        emoji = "📈" if change > 0 else "📉"
        hacim_txt = f"{oran:.1f}x normal" if oran else "bilinmiyor"
        telegram_gonder(
            f"📡 RADAR — HABERSİZ HAREKET\n"
            f"🏢 {desc} ({kod})\n"
            f"{emoji} Değişim: {change:+.1f}% | Hacim: {hacim_txt} | Fiyat: {close} TL\n"
            f"🕐 {simdi.strftime('%H:%M')}\n"
            f"📰 KAP kontrol: Son 24 saatte haber YOK → hareket haberin önünde\n"
            f"🔎 Söylenti/sektör etkisi olabilir; yatırım tavsiyesi değildir.")
        alerts[kod] = simdi.isoformat()
        gonderilen += 1
        print("Radar uyarsi:", kod, f"{change:+.1f}%")
        try:
            lt = radar_track_oku()
            lt.append({"kod": kod, "desc": desc, "baz": float(close),
                       "degisim": change,
                       "hedef_t": (simdi + timedelta(hours=48)).isoformat(),
                       "done": False})
            radar_track_yaz(lt)
            print("Radar takibe eklendi:", kod)
        except (TypeError, ValueError):
            pass

    alerts = {k: v for k, v in alerts.items()
              if simdi - datetime.fromisoformat(v) < timedelta(days=7)}
    state["alerts"] = alerts
    state_yaz(state)

    if manuel:
        satirlar = ["📡 RADAR TEST (anlik en cok hareketliler):"]
        for item in yukan[:5]:
            kod = item.get("s", "?")
            d = item.get("d", [])
            dur = "haber VAR" if kod in kap_kodlari else "haber YOK"
            try:
                yuzde = f"%{float(d[2]):.1f}"
            except (TypeError, ValueError, IndexError):
                yuzde = "?"
            satirlar.append(f"• {kod} | {d[0] if d else '?'} | {yuzde} | KAP 24h: {dur}")
        telegram_gonder("\n".join(satirlar))
    print(f"Bu turda {gonderilen} radar uyarisi gonderildi")

radar_tur(manuel=(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"))
