import os
import json
import requests
from datetime import datetime, timedelta, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))

SCANNER = "https://scanner.tradingview.com/turkey/scan"
STATE   = "rider_state.json"
TRACK   = "rider_track.json"

ST_PERIOD = 10
ST_MULT   = 3.0
SERT_STOP = 0.93
MAKS_GUN  = 20
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

def bars(kod, range_="6mo"):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{kod}.IS"
        r = requests.get(url, params={"range": range_, "interval": "1d"}, headers=HEADERS, timeout=30)
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

def oku(path, bos=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return [] if bos is None else bos

def yaz(path, veri):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False)

def aday_tara():
    body = {
        "columns": ["description", "close", "change", "volume", "relative_volume_10d_calc"],
        "filter": [
            {"left": "change", "operation": "greater", "right": 0},
            {"left": "change", "operation": "less", "right": 9.8},
            {"left": "relative_volume_10d_calc", "operation": "greater", "right": 1.5},
            {"left": "volume", "operation": "greater", "right": 50000},
        ],
        "sort": {"sortBy": "volume", "sortOrder": "desc"},
        "range": [0, 40],
        "options": {"lang": "tr"},
    }
    r = requests.post(SCANNER, json=body, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])

def pozisyonlari_yonet(simdi):
    state = oku(STATE, {"sent": {}, "positions": []})
    if not isinstance(state, dict):
        state = {"sent": {}, "positions": []}
    pos = state.get("positions", [])
    if not pos:
        return state
    kalan = []
    for p in pos:
        b = bars(p["kod"], "3mo")
        if not b:
            kalan.append(p)
            continue
        c = b[-1][3]
        dirn, line = supertrend(b)
        cikis = None
        try:
            gun = (simdi.date() - datetime.fromisoformat(p["entry_t"]).date()).days
        except Exception:
            gun = 0
        if dirn is not None and dirn[-1] == -1:
            cikis = "Supertrend aşağı döndü"
        elif c <= p["entry"] * SERT_STOP:
            cikis = "Sert stop (-7%)"
        elif gun > int(MAKS_GUN * 1.5):
            cikis = f"{MAKS_GUN} işlem günü doldu"
        if cikis:
            fark = (c - p["entry"]) / p["entry"] * 100
            emoji = "📈" if fark > 0 else "📉"
            telegram_gonder(
                f"🐻 RIDER ÇIKIŞ\n"
                f"🏢 {p['desc']} ({p['kod']})\n"
                f"💰 Giriş: {p['entry']:.2f} → Çıkış: {c:.2f} TL\n"
                f"{emoji} Getiri: {fark:+.2f}% | Sebep: {cikis}\n"
                f"📒 Deftere işlendi (rider hanesi).")
            tr = oku(TRACK, [])
            tr.append({"kod": p["kod"], "desc": p["desc"], "baz": p["entry"], "son": c,
                       "fark": round(fark, 2), "tip": "rider", "done": True})
            yaz(TRACK, tr)
        else:
            kalan.append(p)
    state["positions"] = kalan
    yaz(STATE, state)
    return state

def tur(manuel=False):
    simdi = datetime.now(TRT)
    state = pozisyonlari_yonet(simdi)
    if not manuel and not seans_icinde_mi():
        print("Seans disinda rider uyuyor (pozisyon yonetimi yapildi).")
        return
    try:
        adaylar = aday_tara()
    except Exception as e:
        print("Scanner hatasi:", e)
        return
    sent = state.get("sent", {})
    acik_kodlar = {p["kod"] for p in state.get("positions", [])}
    gonderilen = 0
    for item in adaylar:
        if gonderilen >= 3:
            break
        kod = (item.get("s") or "").strip()
        d = item.get("d", [])
        if not kod or len(d) < 5 or kod in acik_kodlar:
            continue
        son_u = sent.get(kod)
        if son_u:
            try:
                if simdi - datetime.fromisoformat(son_u) < timedelta(hours=SESSIZLIK_SAAT):
                    continue
            except Exception:
                pass
        desc, close, change, vol, rvol = d[0], d[1], d[2], d[3], d[4]
        try:
            close_f = float(close)
            vol_f = float(vol)
        except (TypeError, ValueError):
            continue
        if close_f * vol_f < 5_000_000:
            continue
        b = bars(kod, "6mo")
        dirn, line = supertrend(b)
        if dirn is None or len(dirn) < 2:
            continue
        taze_donme = dirn[-1] == 1 and dirn[-2] == -1
        yesil_mum = b[-1][3] >= b[-1][4]
        if not (taze_donme and yesil_mum):
            continue
        stop = line[-1]
        telegram_gonder(
            f"🐂 RIDER GİRİŞ — TREND DÖNÜŞÜ ONAYLI\n"
            f"🏢 {desc} ({kod})\n"
            f"💰 Giriş referansı: {close_f:.2f} TL | 🛡 Supertrend stop: {stop:.2f} TL ({(stop / close_f - 1) * 100:+.1f}%)\n"
            f"📊 Koşullar: Supertrend yukarı döndü + yeşil mum + hacim {rvol:.1f}x\n"
            f"🎯 Kural: trend kırılınca ya da -7% / 20 günde çık; sonuç deftere.")
        sent[kod] = simdi.isoformat()
        state.setdefault("positions", []).append(
            {"kod": kod, "desc": desc, "entry": close_f, "stop": stop,
             "entry_t": simdi.date().isoformat()})
        gonderilen += 1
        print("Rider girisi:", kod)
    state["sent"] = sent
    yaz(STATE, state)
    if manuel and gonderilen == 0:
        telegram_gonder("🐂 RIDER TEST: bugün taze trend dönüşü + onay yok (sistem nakitte bekliyor — bu da bir pozisyondur).")
    print(f"{gonderilen} rider girisi bildirildi")

tur(manuel=(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"))
