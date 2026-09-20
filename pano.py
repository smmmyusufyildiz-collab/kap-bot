import os
import requests
from datetime import datetime, timedelta, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))

SCANNER = "https://scanner.tradingview.com/turkey/scan"
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

def pano():
    simdi = datetime.now(TRT)
    if simdi.weekday() >= 5:
        print("Hafta sonu pano yok.")
        return
    try:
        body = {
            "columns": ["description", "close", "change", "volume", "relative_volume_10d_calc"],
            "filter": [{"left": "volume", "operation": "greater", "right": 50000}],
            "sort": {"sortBy": "volume", "sortOrder": "desc"},
            "range": [0, 80],
            "options": {"lang": "tr"},
        }
        r = requests.post(SCANNER, json=body, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json().get("data", [])
    except Exception as e:
        print("Scanner hatasi:", e)
        return
    taze = []
    trend = []
    for item in data[:80]:
        kod = (item.get("s") or "").strip()
        d = item.get("d", [])
        if not kod or len(d) < 5:
            continue
        desc, close, change, vol, rvol = d[0], d[1], d[2], d[3], d[4]
        try:
            close_f = float(close)
            vol_f = float(vol)
        except (TypeError, ValueError):
            continue
        if close_f * vol_f < 5_000_000:
            continue
        b = bars(kod)
        dirn, line = supertrend(b)
        if dirn is None or len(dirn) < 2:
            continue
        if dirn[-1] == 1 and dirn[-2] == -1 and close_f >= b[-1][4]:
            taze.append((kod, desc, close_f, rvol))
        elif dirn[-1] == 1:
            trend.append(kod)
    satirlar = ["🐂 GÜNLÜK AL SİNYALİ PANOSU (Supertrend 10-3, özgür klon)"]
    if taze:
        satirlar.append("🆕 Bugün taze dönüş + onay mumu:")
        for kod, desc, close_f, rvol in taze[:10]:
            satirlar.append(f"• {kod} | {desc[:24]} | {close_f:.2f} TL | hacim {rvol:.1f}x")
    else:
        satirlar.append("🆕 Bugün taze dönüş yok — piyasa ya düşüşte ya da beklemede.")
    satirlar.append(f"✅ Trendi hâlâ yukarıda olanlar ({len(trend)}): {', '.join(trend[:12]) or '-'}")
    satirlar.append("🔎 Bu pano B/C indikatörlerinin mantık klonudur; yatırım tavsiyesi değildir.")
    tg("\n".join(satirlar))
    print("Pano gonderildi:", len(taze), "taze,", len(trend), "trend")

pano()
