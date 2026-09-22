import os
import requests
from datetime import datetime, timedelta, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))

SCANNER = "https://scanner.tradingview.com/turkey/scan"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}

def tg(mesaj):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": mesaj, "disable_web_page_preview": True},
                      timeout=15)
    except Exception as e:
        print("Telegram hatasi:", e)

def vol_pano(manuel=False):
    simdi = datetime.now(TRT)
    if simdi.weekday() >= 5:
        print("Hafta sonu vol pano yok.")
        return
    body = {
        "columns": ["description", "close", "change", "volume", "relative_volume_10d_calc", "Volatility.D"],
        "filter": [
            {"left": "Volatility.D", "operation": "greater", "right": 6},
            {"left": "change", "operation": "greater", "right": -9.8},
            {"left": "change", "operation": "less", "right": 9.8},
            {"left": "volume", "operation": "greater", "right": 100000},
        ],
        "sort": {"sortBy": "Volatility.D", "sortOrder": "desc"},
        "range": [0, 25],
        "options": {"lang": "tr"},
    }
    try:
        r = requests.post(SCANNER, json=body, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json().get("data", [])
    except Exception as e:
        print("Scanner hatasi:", e)
        if manuel:
            tg(f"⚡ VOL HAVUZU TEST: tarayıcıya ulaşılamadı ({e.__class__.__name__}).")
        return
    satirlar = ["⚡ GÜNLÜK AL-SAT HAVUZU — yüksek volatilite + likidite",
                "💬 Özünde: günde ortalama %6+ salınan VE cirosu yeterli hisseler; indikatör testi için uygun, 'yatırım' için değil."]
    n = 0
    for item in data:
        kod = (item.get("s") or "").strip()
        d = item.get("d", [])
        if not kod or len(d) < 6:
            continue
        desc, close, change, vol, rvol, vold = d
        try:
            close_f = float(close)
            vol_f = float(vol)
            vold_f = float(vold)
        except (TypeError, ValueError):
            continue
        ciro = close_f * vol_f
        if ciro < 10_000_000:
            continue
        satirlar.append(f"• {kod} | {close_f:.2f} TL | bugün {change:+.1f}% | günlük salınım %{vold_f:.1f} | ciro {ciro / 1e6:.0f}M TL")
        n += 1
        if n >= 12:
            break
    if n == 0:
        satirlar.append("• Eşiğe uyan hisse yok.")
    satirlar.append("⚠️ Kural: volatilite iki taraflı bıçaktır; ±10% limit kilidi çıkışını kapatabilir; komisyon+makas küçük hareketi yer; önce küçük boyutla test.")
    satirlar.append("❓ Ne yapmalı: Bu bir AL listesi değildir. İndikatörünü bu havuzda dene; her işlemi (kod, giriş, çıkış) gün sonunda bana yaz, deftere 'VolTest' kaynağıyla işleyeyim.")
    tg("\n".join(satirlar))
    print("Vol pano gonderildi,", n, "hisse")

vol_pano(manuel=(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"))
