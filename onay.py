import os
import re
import json
import requests
from datetime import datetime, timedelta, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))

STATE = "onay_state.json"
CAGRI = "cagrilar.json"
TRACK = "taban_track.json"
GECERLILIK_SAAT = 72
ST_PERIOD = 10
ST_MULT   = 3.0

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

def updates_get(offset):
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                         params={"offset": offset, "limit": 100}, timeout=30)
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception as e:
        print("getUpdates hatasi:", e)
        return []

def fiyat(kod):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{kod}.IS"
        r = requests.get(url, params={"range": "5d", "interval": "1d"}, headers=HEADERS, timeout=20)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        meta = res.get("meta", {})
        p = meta.get("regularMarketPrice")
        if p:
            return float(p)
        closes = [c for c in res["indicators"]["quote"][0].get("close", []) if c is not None]
        return float(closes[-1]) if closes else None
    except Exception as e:
        print("Fiyat hatasi:", kod, e)
        return None

def bars(kod):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{kod}.IS"
        r = requests.get(url, params={"range": "6mo", "interval": "1d"}, headers=HEADERS, timeout=30)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        ts = res.get("timestamp", [])
        q = res["indicators"]["quote"][0]
        hi, lo, cl, op = q.get("high", []), q.get("low", []), q.get("close", []), q.get("open", [])
        out = []
        for t, h, l, c, o in zip(ts, hi, lo, cl, op):
            if c is None or h is None or l is None:
                continue
            out.append((datetime.fromtimestamp(t, TRT).date(), float(h), float(l), float(c),
                        float(o) if o is not None else float(c)))
        return out
    except Exception as e:
        print("Bars hatasi:", kod, e)
        return []

def supertrend(b):
    n = len(b)
    if n < ST_PERIOD + 3:
        return None, None
    tr = [0.0] * n
    for i in range(1, n):
        h, l, c = b[i][1], b[i][2], b[i][3]
        pc = b[i - 1][3]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr = [0.0] * n
    atr[ST_PERIOD] = sum(tr[1:ST_PERIOD + 1]) / ST_PERIOD
    for i in range(ST_PERIOD + 1, n):
        atr[i] = (atr[i - 1] * (ST_PERIOD - 1) + tr[i]) / ST_PERIOD
    dirn = [0] * n
    line = [0.0] * n
    fu = [0.0] * n
    fl = [0.0] * n
    for i in range(ST_PERIOD, n):
        h, l, c = b[i][1], b[i][2], b[i][3]
        mid = (h + l) / 2.0
        bu = mid + ST_MULT * atr[i]
        bl = mid - ST_MULT * atr[i]
        fu[i] = bu if (i == ST_PERIOD or bu < fu[i - 1] or b[i - 1][3] > fu[i - 1]) else fu[i - 1]
        fl[i] = bl if (i == ST_PERIOD or bl > fl[i - 1] or b[i - 1][3] < fl[i - 1]) else fl[i - 1]
        if i == ST_PERIOD:
            dirn[i] = 1 if c > fu[i] else -1
        elif dirn[i - 1] == 1:
            dirn[i] = -1 if c < fl[i] else 1
        else:
            dirn[i] = 1 if c > fu[i] else -1
        line[i] = fl[i] if dirn[i] == 1 else fu[i]
    return dirn, line

def onay_karti(kod, kaynaklar, simdi, state):
    p = fiyat(kod)
    b = bars(kod)
    dirn, line = supertrend(b)
    st_txt = "YUKARI" if (dirn and dirn[-1] == 1) else ("AŞAĞI" if dirn else "bilinmiyor")
    tab = oku(TRACK, [])
    havuzda = any((t.get("kod") == kod and not t.get("done")) for t in tab)
    cagrilar = oku(CAGRI, [])
    for ch in kaynaklar:
        key = f"{ch}|{kod}|{simdi.date().isoformat()}"
        if key not in state.setdefault("cagri_keys", []):
            cagrilar.append({"tarih": simdi.date().isoformat(),
                             "kaynak": f"Indikator-{ch} (mühür)", "kod": kod,
                             "soylenen": round(p, 2) if p else None, "pencere": 10})
            state["cagri_keys"].append(key)
    yaz(CAGRI, cagrilar)
    fiyat_txt = f"{p:.2f} TL" if p else "alınamadı"
    tg(
        f"🔔 ONAY İŞLENDİ — {kod} ({kaynaklar})\n"
        f"💬 Özünde: İndikatör onayını mühürledin; anlık fiyat {fiyat_txt}.\n"
        f"🐂 Bizim klon (Supertrend 10-3): trend {st_txt}.\n"
        f"🔄 Taban havuzu: {'içinde' if havuzda else 'dışında'}.\n"
        f"📒 Deftere işlendi: kaynak 'Indikator-{kaynaklar} (mühür)', 10 gün sonra hüküm karnede.\n"
        f"❓ Ne yapmalı: Bu tek tanık ifadesi; diğer indikatör de onaylarsa 🤝 ÇİFT ONAY ayrıca düşer. Karar kartı istersen ekran görüntüsü at.")

def tur(manuel=False):
    state = oku(STATE, {"last": 0, "onaylar": {}, "logged": [], "cagri_keys": []})
    if not isinstance(state, dict):
        state = {"last": 0, "onaylar": {}, "logged": [], "cagri_keys": []}
    last = state.get("last", 0)
    for u in updates_get(last + 1):
        last = max(last, u.get("update_id", last))
        msg = u.get("message") or {}
        text = (msg.get("text") or "").strip().upper()
        m = re.fullmatch(r"([BC]{1,2})\+\s+([A-Z0-9]{3,6})", text)
        if m:
            kaynaklar, kod = m.group(1), m.group(2)
            rec = state.setdefault("onaylar", {}).setdefault(kod, {})
            for ch in kaynaklar:
                rec[ch] = datetime.now(TRT).isoformat()
            print("Onay kaydi:", kaynaklar, kod)
            onay_karti(kod, kaynaklar, datetime.now(TRT), state)
            continue
        if text == "LISTE":
            satirlar = ["🤝 ONAY DEFTERİ:"]
            onaylar = state.get("onaylar", {})
            if not onaylar:
                satirlar.append("(boş — format: B+ KOD / C+ KOD / BC+ KOD)")
            for kod, rec in onaylar.items():
                b, c = rec.get("B"), rec.get("C")
                satirlar.append(f"• {kod}: B={b[:16] if b else '-'} | C={c[:16] if c else '-'}")
            tg("\n".join(satirlar))
    state["last"] = last

    simdi = datetime.now(TRT)
    eklenen = []
    for kod, rec in state.get("onaylar", {}).items():
        b, c = rec.get("B"), rec.get("C")
        if not b or not c:
            continue
        tb, tc = datetime.fromisoformat(b), datetime.fromisoformat(c)
        if simdi - tb > timedelta(hours=GECERLILIK_SAAT) or simdi - tc > timedelta(hours=GECERLILIK_SAAT):
            continue
        anahtar = f"{kod}|{b[:10]}|{c[:10]}"
        if anahtar in state.get("logged", []):
            continue
        p = fiyat(kod)
        if not p:
            continue
        cagrilar = oku(CAGRI, [])
        cagrilar.append({"tarih": simdi.date().isoformat(),
                         "kaynak": "ÇİFT ONAY (B+C)", "kod": kod,
                         "soylenen": round(p, 2), "pencere": 10})
        yaz(CAGRI, cagrilar)
        state.setdefault("logged", []).append(anahtar)
        eklenen.append((kod, p, tb, tc))
    yaz(STATE, state)

    for kod, p, tb, tc in eklenen:
        tg(
            f"🤝 ÇİFT ONAY — B ve C aynı hissede buluştu\n"
            f"🏢 {kod}\n"
            f"💰 Referans fiyat: {p:.2f} TL\n"
            f"🕐 B onay: {tb.strftime('%d %b %H:%M')} | C onay: {tc.strftime('%d %b %H:%M')}\n"
            f"📒 Deftere işlendi: kaynak 'ÇİFT ONAY (B+C)' — 10 işlem günü sonra hüküm karnede.")
    if manuel and not eklenen:
        tg("🤝 ONAY TEST: sistem ayakta. Format: 'B+ KOD', 'C+ KOD' veya 'BC+ KOD'; durum için 'LISTE'.")
    print("Tur bitti, yeni cift onay:", len(eklenen))

tur(manuel=(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"))
