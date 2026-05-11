#!/usr/bin/env python3
"""
Corner Prophet - Napi Becslés v0.5
Fut: minden nap 08:00 UTC (10:00 Budapest)
1. Lekéri az aznapi PL meccseket
2. Lefuttatja a modellt
3. Elmenti predictions/history.json-ba
4. Elküldi Telegramra
"""

import json, urllib.request, os, sys, math
from datetime import datetime, timezone

FDORG_TOKEN   = os.environ.get("FDORG_TOKEN", "")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

DATA_DIR = "data"
PRED_DIR = "predictions"
HIST_FILE = f"{PRED_DIR}/history.json"
SUM_FILE  = f"{PRED_DIR}/summary.json"

CSV_FILES = {
    "2025/26": f"{DATA_DIR}/E0_2526.csv",
    "2024/25": f"{DATA_DIR}/E0_2425.csv",
    "2023/24": f"{DATA_DIR}/E0_2324.csv",
}
SEASON_W = {"2025/26": 0.6, "2024/25": 0.3, "2023/24": 0.1}

# ── HELPERS ───────────────────────────────────────────────────────────────────

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def api_get(url):
    req = urllib.request.Request(url, headers={"X-Auth-Token": FDORG_TOKEN})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

# ── CSV BETÖLTÉS ──────────────────────────────────────────────────────────────

def load_matches():
    all_matches = []
    for season, path in CSV_FILES.items():
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().strip().split("\n")
        if len(lines) < 2:
            continue
        hdrs = [h.strip() for h in lines[0].split(",")]
        hi, ai = hdrs.index("HomeTeam"), hdrs.index("AwayTeam")
        hci, aci = hdrs.index("HC"), hdrs.index("AC")
        di = hdrs.index("Date") if "Date" in hdrs else -1
        for line in lines[1:]:
            v = line.split(",")
            if len(v) <= max(hi, ai, hci, aci):
                continue
            try:
                hc, ac = float(v[hci]), float(v[aci])
            except ValueError:
                continue
            all_matches.append({
                "home": v[hi].strip(), "away": v[ai].strip(),
                "HC": hc, "AC": ac,
                "date": v[di].strip() if di >= 0 else "",
                "_s": season,
            })
    return all_matches

# ── MODELL ────────────────────────────────────────────────────────────────────

def sw(m):
    return SEASON_W.get(m["_s"], 0.1)

def parse_date(d):
    if not d: return 0
    p = d.split("/")
    if len(p) == 3:
        y = (1900 if int(p[2]) > 50 else 2000) + int(p[2]) if len(p[2]) == 2 else int(p[2])
        return datetime(y, int(p[1]), int(p[0])).timestamp()
    try: return datetime.fromisoformat(d).timestamp()
    except: return 0

def get_ms(matches, team, role, w=7):
    ms = [m for m in matches if (m["home"] if role=="home" else m["away"]) == team]
    ms.sort(key=lambda m: parse_date(m["date"]), reverse=True)
    return ms[:w]

def wavg(matches, val_fn):
    if not matches: return 0
    total = ws = 0
    for i, m in enumerate(matches):
        w = sw(m) * (len(matches) - i)
        total += val_fn(m) * w; ws += w
    return total / ws if ws else 0

def tact_def(matches, team, role):
    curr = [m for m in matches if m["_s"]=="2024/25" and (m["home"] if role=="home" else m["away"])==team]
    if not curr: curr = [m for m in matches if (m["home"] if role=="home" else m["away"])==team]
    if not curr: return 1.0
    conceded = [m["AC"] if role=="home" else m["HC"] for m in curr]
    team_avg = sum(conceded) / len(conceded)
    lg = [m for m in matches if m["_s"]=="2024/25"] or matches
    lg_vals = [m["AC"] if role=="home" else m["HC"] for m in lg]
    lg_avg = sum(lg_vals) / len(lg_vals) if lg_vals else 1
    return team_avg / lg_avg if lg_avg else 1.0

def lg_avgs(matches):
    wH = wA = wS = 0
    for m in matches:
        w = sw(m); wH += m["HC"]*w; wA += m["AC"]*w; wS += w
    return (wH/wS if wS else 5), (wA/wS if wS else 5)

def poisson_p(lam, k):
    if lam <= 0: return 1.0 if k==0 else 0.0
    return math.exp(-lam + k*math.log(lam) - sum(math.log(i) for i in range(1,k+1)))

def poisson_over(lH, lA, t):
    p = 0
    for h in range(36):
        for a in range(36):
            if h+a > t: p += poisson_p(lH,h) * poisson_p(lA,a)
    return min(p, 1)

def predict(matches, home, away):
    hH = get_ms(matches, home, "home")
    aA = get_ms(matches, away, "away")
    if not hH or not aA: return None
    lgH, lgA = lg_avgs(matches)
    hAtk = wavg(hH, lambda m: m["HC"]) / lgH if lgH else 1
    aAtk = wavg(aA, lambda m: m["AC"]) / lgA if lgA else 1
    hDef = tact_def(matches, home, "home")
    aDef = tact_def(matches, away, "away")
    pH = round(lgH * hAtk * aDef, 2)
    pA = round(lgA * aAtk * hDef, 2)
    pT = round(pH + pA, 2)
    thresholds = [6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5]
    probs = {str(t): round(poisson_over(pH, pA, t)*100, 1) for t in thresholds}
    return {"pH": pH, "pA": pA, "pT": pT, "probs": probs}

# ── NAME MAPPING ──────────────────────────────────────────────────────────────

NAME_MAP = {
    "Arsenal": "Arsenal", "Chelsea": "Chelsea", "Liverpool": "Liverpool",
    "Man United": "Man United", "Man City": "Man City", "Tottenham": "Tottenham",
    "Newcastle": "Newcastle", "Aston Villa": "Aston Villa", "Brighton": "Brighton",
    "West Ham": "West Ham", "Brentford": "Brentford", "Fulham": "Fulham",
    "Crystal Palace": "Crystal Palace", "Everton": "Everton", "Wolves": "Wolves",
    "Bournemouth": "Bournemouth", "Nott'm Forest": "Nott'm Forest",
    "Leicester": "Leicester", "Ipswich": "Ipswich", "Southampton": "Southampton",
    "Leeds": "Leeds", "Burnley": "Burnley", "Luton": "Luton",
    "Sheffield Utd": "Sheffield United", "Sheffield United": "Sheffield United",
}

# ── FOOTBALL-DATA.ORG ─────────────────────────────────────────────────────────

def get_fixtures(date_from, date_to, status="SCHEDULED"):
    url = f"https://api.football-data.org/v4/competitions/PL/matches?dateFrom={date_from}&dateTo={date_to}&status={status}"
    try:
        return api_get(url).get("matches", [])
    except Exception as e:
        print(f"API hiba: {e}"); return []

# ── SUMMARY FRISSÍTÉS ─────────────────────────────────────────────────────────

def update_summary():
    hist = load_json(HIST_FILE, [])
    done = [e for e in hist if e.get("actualT") is not None]
    if not done:
        save_json(SUM_FILE, {"evaluated": 0, "mae": None, "bias": None, "acc": {}})
        return
    n = len(done)
    errors = [e["predT"] - e["actualT"] for e in done]
    mae = round(sum(abs(x) for x in errors) / n, 3)
    bias = round(sum(errors) / n, 3)
    acc = {}
    for t in ["6.5","7.5","8.5","9.5","10.5","11.5","12.5"]:
        relevant = [e for e in done if e.get("probs") and t in e["probs"]]
        if not relevant: continue
        correct = sum(1 for e in relevant if
            (e["probs"][t] >= 50 and e["actualT"] > float(t)) or
            (e["probs"][t] < 50 and e["actualT"] <= float(t)))
        acc[t] = round(correct / len(relevant) * 100, 1)
    summary = {"evaluated": n, "mae": mae, "bias": bias, "acc": acc,
               "updatedAt": datetime.now(timezone.utc).isoformat()}
    save_json(SUM_FILE, summary)
    print(f"Summary: n={n}, MAE={mae}, bias={bias}")

# ── TELEGRAM ──────────────────────────────────────────────────────────────────

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("WARN: Telegram credentials missing"); return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        print(f"Telegram: {r.status}")

def format_telegram(fixtures, predictions, today):
    lines = [
        "⚽ *Corners Prediction — Napi jelentés*",
        f"📅 {today} | Premier League",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]
    if not fixtures:
        lines.append("\nMa nincs Premier League mérkőzés.")
        lines.append("\n_Daily Corners v0.5 • Csak tájékoztató célra_")
        return "\n".join(lines)
    for fix in fixtures:
        home_raw = fix["homeTeam"]["shortName"]
        away_raw = fix["awayTeam"]["shortName"]
        time_str = fix["utcDate"][11:16]
        pred = predictions.get(f"{home_raw}|{away_raw}")
        lines.append(f"\n🕐 {time_str} UTC | *{home_raw} vs {away_raw}*")
        if pred:
            lines.append(f"📐 Várható szögletek: {pred['pH']} + {pred['pA']} = *{pred['pT']}*")
            lines.append("📈 Poisson valószínűségek:")
            for t, p in pred["probs"].items():
                under = round(100 - p, 1)
                icon = "🟢" if p >= 60 else "🟡" if p >= 40 else "🔴"
                lines.append(f"  {icon} Felett {t}: *{p}%* / Alatt: {under}%")
        else:
            lines.append("  ⚠️ Nincs elegendő adat")
        lines.append("─────────────────────")
    lines.append("\n_Daily Corners v0.5 • Csak tájékoztató célra_")
    return "\n".join(lines)

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"Corner Prophet Napi Becslés — {today}")

    matches = load_matches()
    print(f"Betöltött meccsek: {len(matches)}")

    fixtures = get_fixtures(today, today)
    print(f"Mai PL meccsek: {len(fixtures)}")

    predictions = {}
    hist = load_json(HIST_FILE, [])
    existing_ids = {e["id"] for e in hist}

    for fix in fixtures:
        home_raw = fix["homeTeam"]["shortName"]
        away_raw = fix["awayTeam"]["shortName"]
        home = NAME_MAP.get(home_raw, home_raw)
        away = NAME_MAP.get(away_raw, away_raw)
        entry_id = f"{today}_{home_raw.replace(' ','')}_{away_raw.replace(' ','')}"

        pred = predict(matches, home, away)
        if pred:
            predictions[f"{home_raw}|{away_raw}"] = pred
            print(f"  {home} vs {away}: {pred['pT']}")
            # Csak akkor mentjük ha még nem szerepel
            if entry_id not in existing_ids:
                hist.insert(0, {
                    "id": entry_id,
                    "date": today,
                    "savedAt": datetime.now(timezone.utc).isoformat(),
                    "home": home_raw, "away": away_raw,
                    "homeCSV": home, "awayCSV": away,
                    "predH": pred["pH"], "predA": pred["pA"], "predT": pred["pT"],
                    "probs": pred["probs"],
                    "actualH": None, "actualA": None, "actualT": None,
                    "error": None,
                    "matchId": fix.get("id")
                })
        else:
            print(f"  {home} vs {away}: nincs adat")

    save_json(HIST_FILE, hist)
    update_summary()

    tg = format_telegram(fixtures, predictions, today)
    send_telegram(tg)
    print("Kész!")

if __name__ == "__main__":
    main()
