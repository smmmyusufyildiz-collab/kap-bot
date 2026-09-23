import os
import json
import requests
from datetime import datetime, timedelta, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))

TRACK = "taban_track.json"
STATE = "takip_state.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}

def tg(mesaj):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": mesaj, "disable_web_page_preview": True},
                      timeout=15)
    except Exception as e:
        print("Telegram hatasi:", e)

def oku(path, bos=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return [] if bos is None else bos

def yaz(path, veri):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False)

def fiyat(kod):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{kod}.IS"
        r = requests.get(url, params={"range": "5d", "interval": "1d"}, headers=HEADERS, timeout=20)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        p = res.get("meta", {}).get("regularMarketPrice")
        if p:
            return float(p)
        closes = [c for c in res["indicators"]["quote"][0].get("close", []) if c is not None]
        return float(closes[-1]) if closes else None
    except Exception as e:
        print("Fiyat hatasi:", kod, e)
        return None

def kivilcim(kod):
    for deneme in range(2):
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{kod}.IS"
            r = requests.get(url, params={"range": "5d", "interval": "1d"}, headers=HEADERS, timeout=20)
            r.raise_for_status()
            q = r.json()["chart"]["result"][0]["indicators"]["quote"][0]
            for o, c in reversed(list(zip(q.get("open", []), q.get("close", [])))):
                if o and c:
                    return (c - o) / o * 100
            return None
        except Exception as e:
            print("Kivilcim deneme hatasi:", kod, deneme, e)
    return None

def tur(manuel=False):
    simdi = datetime.now(TRT)
    if not manuel and simdi.weekday() >= 5:
        return
    state = oku(STATE, {"takip": {}})
    if not isinstance(state, dict):
        state = {"takip": {}}
    track = oku(TRACK, [])

    for t in track:
        kod = (t.get("kod") or "").strip()
        if not kod:
            continue
        key = f"{kod}|{t.get('tarih', t.get('ts', ''))}"
        if key not in state["takip"]:
            p = fiyat(kod)
            if p:
                state["takip"][key] = {"kod": kod, "t0": simdi.isoformat(), "p0": p, "flags": {}}
                print("Takip basladi:", kod, p)

    kapanan = []
    for key, e in state["takip"].items():
        kod = e["kod"]
        p0 = e["p0"]
        t0 = datetime.fromisoformat(e["t0"])
        yas = simdi - t0
        p = fiyat(kod)
        if not p:
            continue
        chg = (p - p0) / p0 * 100
        flags = e.setdefault("flags", {})
        if yas <= timedelta(hours=24):
            if chg <= -3 and "dus" not in flags:
                flags["dus"] = 1
                tg(f"📉 TAKİP — {kod}\n💬 Özünde: ucuz izleme uyarısından bu yana düşüş sürüyor ({chg:+.1f}%). Bıçak hâlâ düşüyor.\n❓ Ne yapmalı: hiçbir şey; kıvılcım yanmadan dokunma.")
            if chg >= 3 and "tepki" not in flags:
                flags["tepki"] = 1
                tg(f"📈 TAKİP — {kod}\n💬 Özünde: uyarı fiyatına göre tepki yükselişi başladı ({chg:+.1f}%).\n❓ Ne yapmalı: kıvılcım teyidine bak; 🔥 mesajı da geldiyse kova güçlenir.")
            sp = kivilcim(kod)
            if sp is not None and sp > 0.5 and "kivilcim" not in flags:
                flags["kivilcim"] = 1
                tg(f"🔥 TAKİP — {kod}\n💬 Özünde: dönüş kıvılcımı yandı (açılışa göre {sp:+.1f}%).\n❓ Ne yapmalı: artık 'düşünülür' kova; karar kartı istersen ekran görüntüsü at.")
        else:
            tg(f"⏱️ 24-SAAT TAKİP RAPORU — {kod}\n💬 Özünde: uyarı fiyatı {p0:.2f} → şimdi {p:.2f} ({chg:+.1f}%). Kıvılcım: {'yandı 🔥' if 'kivilcim' in flags else 'yanmadı'}.\n📒 Takip kapandı; 48 saatlik sonuç raporu ayrıca gelecek.")
            kapanan.append(key)
    for key in kapanan:
        del state["takip"][key]
    yaz(STATE, state)
    print("Takip turu bitti. Aktif:", len(state["takip"]))

tur(manuel=(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"))
