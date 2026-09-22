import os
import json
import requests
from datetime import datetime, timedelta, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TRT = timezone(timedelta(hours=3))

SCANNER = "https://scanner.tradingview.com/turkey/scan"
STATE   = "mom_state.json"

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

def mom_tur(manuel=False):
    simdi = datetime.now(TRT)
    if not manuel and simdi.weekday() >= 5:
        return
    body = {
        "columns": ["description", "close", "change", "volume", "relative_volume_10d_calc", "high"],
        "filter": [
            {"left": "change", "operation": "greater", "right": 2},
            {"left": "change", "operation": "less", "right": 9.8},
            {"left": "relative_volume_10d_calc", "operation": "greater", "right": 2},
            {"left": "volume", "operation": "greater", "right": 100000},
        ],
        "sort": {"sortBy": "change", "sortOrder": "desc"},
        "range": [0, 30],
        "options": {"lang": "tr"},
    }
    try:
        r = requests.post(SCANNER, json=body, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json().get("data", [])
    except Exception as e:
        print("Scanner hatasi:", e)
        if manuel:
            tg(f"⚡ MOMENTUM TEST: tarayıcıya ulaşılamadı ({e.__class__.__name__}).")
        return
    state = oku(STATE, {"gun": "", "sent": []})
    bugun = simdi.date().isoformat()
    if state.get("gun") != bugun:
        state = {"gun": bugun, "sent": []}
    canli = []
    solgun = []
    for item in data:
        kod = (item.get("s") or "").strip()
        d = item.get("d", [])
        if not kod or len(d) < 6:
            continue
        desc, close, change, vol, rvol, high = d
        try:
            close_f = float(close)
            vol_f = float(vol)
            high_f = float(high)
            ch = float(change)
            rv = float(rvol)
        except (TypeError, ValueError):
            continue
        if close_f * vol_f < 10_000_000 or high_f <= 0:
            continue
        fade = (high_f - close_f) / high_f * 100
        if fade <= 1.5:
            canli.append((kod, ch, fade, rv, close_f * vol_f / 1e6))
        elif fade > 3:
            solgun.append(kod)
    yeniler = [c for c in canli if c[0] not in state["sent"]]
    if not yeniler and not manuel:
        print("Yeni canli momentum yok")
        return
    satirlar = ["⚡ MOMENTUM PANOSU — seans içi",
                "💬 Özünde: bugün %2+ yukarıda ve hâlâ zirvesine yakın (mesafe <1.5%) = momentum CANLI; zirveden 3%+ uzaklaşan = SOLGUN (dağıtım şüphesi)."]
    if yeniler:
        satirlar.append("🟢 YENİ CANLI:")
        for kod, ch, fade, rv, cirom in yeniler[:8]:
            satirlar.append(f"• {kod} | +{ch:.1f}% | zirveye mesafe %{fade:.1f} | hacim {rv:.1f}x | ciro {cirom:.0f}M TL")
            state["sent"].append(kod)
    else:
        satirlar.append("🟢 Yeni canlı isim yok (öncekiler hâlâ listede).")
    if solgun:
        satirlar.append(f"🥀 Solgunlar (yükseldi, geri verdi): {len(solgun)} → {', '.join(solgun[:6])}")
    satirlar.append("⚠️ Kural: gün içi hareketin çıkışı spike'ın içindedir: +3-4% hedef YA DA 16:30 zaman stopu; momentumu 'yatırıma' çevirme.")
    satirlar.append("❓ Ne yapmalı: Bu bir AL listesi değildir; deneyeceksen küçük boyut ve spike'ta satış planıyla gir.")
    tg("\n".join(satirlar))
    yaz(STATE, state)
    print("Momentum pano:", len(yeniler), "yeni")

mom_tur(manuel=(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"))
