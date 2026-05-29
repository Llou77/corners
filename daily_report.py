#!/usr/bin/env python3
"""
Corner Prophet - Napi Becslés v1.0
Multi-liga támogatás: PL, Ligue 1, La Liga, Bundesliga, Serie A
Fut: minden nap 06:00 UTC
"""

import json, urllib.request, os, sys, math
from datetime import datetime, timezone

FDORG_TOKEN      = os.environ.get("FDORG_TOKEN", "")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

DATA_DIR = "data"
PRED_DIR = "predictions"
HIST_FILE = f"{PRED_DIR}/history.json"
SUM_FILE  = f"{PRED_DIR}/summary.json"

# ── LIGA KONFIGURÁCIÓ ─────────────────────────────────────────────────────────

LEAGUES = {
    "PL":  {"name": "Premier League",  "country": "Anglia",    "fdorg_code": "PL",  "csv_prefix": "E0"},
    "FL1": {"name": "Ligue 1",         "country": "Francia",   "fdorg_code": "FL1", "csv_prefix": "F1"},
    "PD":  {"name": "La Liga",         "country": "Spanyol",   "fdorg_code": "PD",  "csv_prefix": "SP1"},
    "BL1": {"name": "Bundesliga",      "country": "Német",     "fdorg_code": "BL1", "csv_prefix": "D1"},
    "SA":  {"name": "Serie A",         "country": "Olasz",     "fdorg_code": "SA",  "csv_prefix": "I1"},
}

# ── SZEZON SÚLYOZÁS ───────────────────────────────────────────────────────────

TIME_FACTORS = [1.0, 0.6, 0.3]

def calc_season_weights(seasons):
    raw = {}
    for i, s in enumerate(seasons):
        tf = TIME_FACTORS[i] if i < len(TIME_FACTORS) else 0.1
        raw[s["label"]] = s["matches"] * tf
    total = sum(raw.values())
    if not total:
        return {s["label"]: 1/len(seasons) for s in seasons}
    return {label: round(val/total, 4) for label, val in raw.items()}

def load_season_config(league_prefix):
    """Betölti az adott liga szezon konfigurációját."""
    config_path = f"{DATA_DIR}/season_config_{league_prefix}.json"
    # Fallback: alap season_config.json (PL)
    if not os.path.exists(config_path):
        config_path = f"{DATA_DIR}/season_config.json"
    try:
        with open(config_path) as f:
            cfg = json.load(f)
        csv_files = {s["label"]: s["file"] for s in cfg["seasons"]}
        weights = calc_season_weights(cfg["seasons"])
        current_season = cfg.get("current", cfg["seasons"][0]["label"])
        return csv_files, weights, current_season
    except Exception as e:
        print(f"WARN: season_config nem olvasható ({e}), fallback")
        # Generikus fallback
        season_map = {
            "E0": ("2025/26", "2024/25", "2023/24"),
            "F1": ("2025/26", "2024/25", "2023/24"),
            "SP1": ("2025/26", "2024/25", "2023/24"),
            "D1": ("2025/26", "2024/25", "2023/24"),
            "I1": ("2025/26", "2024/25", "2023/24"),
        }
        seasons = season_map.get(league_prefix, ("2025/26", "2024/25", "2023/24"))
        csv_files = {
            seasons[0]: f"{DATA_DIR}/{league_prefix}_2526.csv",
            seasons[1]: f"{DATA_DIR}/{league_prefix}_2425.csv",
            seasons[2]: f"{DATA_DIR}/{league_prefix}_2324.csv",
        }
        weights = {seasons[0]: 0.5, seasons[1]: 0.33, seasons[2]: 0.17}
        return csv_files, weights, seasons[0]

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
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

# ── CSV BETÖLTÉS ──────────────────────────────────────────────────────────────

def load_matches(csv_files, season_weights):
    all_matches = []
    for season, path in csv_files.items():
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().strip().split("\n")
        if len(lines) < 2:
            continue
        hdrs = [h.strip() for h in lines[0].split(",")]
        try:
            hi, ai = hdrs.index("HomeTeam"), hdrs.index("AwayTeam")
            hci, aci = hdrs.index("HC"), hdrs.index("AC")
        except ValueError:
            continue
        di = hdrs.index("Date") if "Date" in hdrs else -1
        for line in lines[1:]:
            v = line.split(",")
            if len(v) <= max(hi, ai, hci, aci):
                continue
            try:
                hc, ac = float(v[hci]), float(v[aci])
            except ValueError:
                continue
            row = {
                "home": v[hi].strip(), "away": v[ai].strip(),
                "HC": hc, "AC": ac,
                "date": v[di].strip() if di >= 0 else "",
                "_s": season,
                "_w": season_weights.get(season, 0.1),
            }
            for f in ['HS','AS','HST','AST','HF','AF','HY','AY']:
                try:
                    fi = hdrs.index(f) if f in hdrs else -1
                    row[f] = float(v[fi]) if fi >= 0 and fi < len(v) and v[fi].strip() else 0.0
                except:
                    row[f] = 0.0
            all_matches.append(row)
    return all_matches

# ── MODELL ────────────────────────────────────────────────────────────────────

def sw(m):
    return m.get("_w", 0.1)

def parse_date(d):
    if not d: return 0
    p = d.split("/")
    if len(p) == 3:
        y = (1900 if int(p[2]) > 50 else 2000) + int(p[2]) if len(p[2]) == 2 else int(p[2])
        try: return datetime(y, int(p[1]), int(p[0])).timestamp()
        except: return 0
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

def tact_def(matches, team, role, current_season):
    """Taktikai védekezési index — az aktuális szezont használja."""
    curr = [m for m in matches if m["_s"] == current_season and
            (m["home"] if role=="home" else m["away"]) == team]
    if not curr:
        curr = [m for m in matches if (m["home"] if role=="home" else m["away"]) == team]
    if not curr: return 1.0
    conceded = [m["AC"] if role=="home" else m["HC"] for m in curr]
    team_avg = sum(conceded) / len(conceded)
    lg = [m for m in matches if m["_s"] == current_season] or matches
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
    try:
        return math.exp(-lam + k*math.log(lam) - sum(math.log(i) for i in range(1,k+1)))
    except:
        return 0.0

def poisson_over(lH, lA, t):
    p = 0
    for h in range(36):
        for a in range(36):
            if h+a > t: p += poisson_p(lH,h) * poisson_p(lA,a)
    return min(p, 1)

def predict(matches, home, away, current_season):
    hH = get_ms(matches, home, "home")
    aA = get_ms(matches, away, "away")
    if not hH or not aA: return None
    lgH, lgA = lg_avgs(matches)

    hBaseAtk = wavg(hH, lambda m: m["HC"]) / lgH if lgH else 1
    aBaseAtk = wavg(aA, lambda m: m["AC"]) / lgA if lgA else 1

    hDef = tact_def(matches, home, "home", current_season)
    aDef = tact_def(matches, away, "away", current_season)

    has_shots = any(m.get("HS",0) > 0 for m in hH)

    def lg_avg_field(field):
        ws = sum(sw(m) for m in matches)
        return sum(m.get(field,0)*sw(m) for m in matches)/ws if ws else 0

    def team_avg_field(ms, field):
        return wavg(ms, lambda m: m.get(field, 0))

    def shot_idx(ms, is_home):
        lg = lg_avg_field("HS" if is_home else "AS")
        if lg < 0.5: return 1.0
        return team_avg_field(ms, "HS" if is_home else "AS") / lg

    def sot_inv_idx(ms, is_home):
        shots = team_avg_field(ms, "HS" if is_home else "AS")
        sot   = team_avg_field(ms, "HST" if is_home else "AST")
        if shots < 0.5: return 1.0
        ratio = sot / shots
        return math.sqrt(0.35 / max(ratio, 0.05))

    def foul_idx(ms, is_home):
        lg = lg_avg_field("AF" if is_home else "HF")
        if lg < 0.5: return 1.0
        return team_avg_field(ms, "AF" if is_home else "HF") / lg

    def yellow_idx(ms):
        lg = lg_avg_field("HY") + lg_avg_field("AY")
        if lg < 0.1: return 1.0
        return (team_avg_field(ms,"HY") + team_avg_field(ms,"AY")) / lg

    W = {"base":0.55, "shot":0.25, "sot":0.08, "foul":0.08, "yell":0.04}

    hCompAtk = (W["base"]*hBaseAtk +
                W["shot"]*(shot_idx(hH,True) if has_shots else 1.0) +
                W["sot"] *(sot_inv_idx(hH,True) if has_shots else 1.0) +
                W["foul"]*foul_idx(hH,True) +
                W["yell"]*yellow_idx(hH))

    aCompAtk = (W["base"]*aBaseAtk +
                W["shot"]*(shot_idx(aA,False) if has_shots else 1.0) +
                W["sot"] *(sot_inv_idx(aA,False) if has_shots else 1.0) +
                W["foul"]*foul_idx(aA,False) +
                W["yell"]*yellow_idx(aA))

    pH = round(lgH * hCompAtk * aDef, 2)
    pA = round(lgA * aCompAtk * hDef, 2)
    pT = round(pH + pA, 2)
    thresholds = [6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5]
    probs = {str(t): round(poisson_over(pH, pA, t)*100, 1) for t in thresholds}
    return {"pH": pH, "pA": pA, "pT": pT, "probs": probs}

# ── FOOTBALL-DATA.ORG ─────────────────────────────────────────────────────────

def get_fixtures(fdorg_code, date_str):
    """Lekéri az adott liga aznapi meccseit."""
    url = f"https://api.football-data.org/v4/competitions/{fdorg_code}/matches?dateFrom={date_str}&dateTo={date_str}&status=SCHEDULED"
    try:
        return api_get(url).get("matches", [])
    except Exception as e:
        print(f"  {fdorg_code} API hiba: {e}")
        return []

# ── SUMMARY FRISSÍTÉS ─────────────────────────────────────────────────────────

def update_summary():
    hist = load_json(HIST_FILE, [])
    done = [e for e in hist if e.get("actualT") is not None]
    if not done:
        save_json(SUM_FILE, {"evaluated": 0, "mae": None, "bias": None, "acc": {}})
        return
    n = len(done)
    errors = [e["predT"] - e["actualT"] for e in done]
    mae   = round(sum(abs(x) for x in errors) / n, 3)
    bias  = round(sum(errors) / n, 3)
    acc = {}
    for t in ["6.5","7.5","8.5","9.5","10.5","11.5","12.5"]:
        rel = [e for e in done if e.get("probs") and t in e["probs"]]
        if not rel: continue
        correct = sum(1 for e in rel if
            (e["probs"][t] >= 50 and e["actualT"] > float(t)) or
            (e["probs"][t] < 50  and e["actualT"] <= float(t)))
        acc[t] = round(correct / len(rel) * 100, 1)
    # Kalibrációs faktor: átlagos torzítás threshold-onként
    cal = {}
    for t in ["9.5", "10.5", "8.5"]:
        rel = [e for e in done if e.get("probs") and t in e["probs"] and e.get("actualT") is not None]
        if len(rel) >= 5:
            pred_probs = [e["probs"][t]/100 for e in rel]
            actual_over = [1 if e["actualT"] > float(t) else 0 for e in rel]
            avg_pred = sum(pred_probs)/len(pred_probs)
            avg_actual = sum(actual_over)/len(actual_over)
            cal[t] = round(avg_actual - avg_pred, 3)
    save_json(SUM_FILE, {
        "evaluated": n, "mae": mae, "bias": bias, "acc": acc,
        "calibration": cal,
        "updatedAt": datetime.now(timezone.utc).isoformat()
    })
    print(f"Summary: n={n}, MAE={mae}, bias={bias}")
    if cal:
        print(f"Kalibráció: {cal}")

# ── TELEGRAM ──────────────────────────────────────────────────────────────────

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("WARN: Telegram credentials missing"); return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"Telegram: {r.status}")
    except Exception as e:
        print(f"Telegram hiba: {e}")

def format_telegram_league(league_name, fixtures, predictions):
    """Egy liga Telegram szekciója."""
    lines = [f"🏟 *{league_name}*"]
    if not fixtures:
        return None  # Ha nincs meccs, nem adjuk hozzá
    for fix in fixtures:
        home_raw = fix["homeTeam"]["shortName"]
        away_raw = fix["awayTeam"]["shortName"]
        time_str = fix["utcDate"][11:16]
        pred = predictions.get(f"{home_raw}|{away_raw}")
        lines.append(f"🕐 {time_str} UTC | *{home_raw} vs {away_raw}*")
        if pred:
            lines.append(f"📐 {pred['pH']} + {pred['pA']} = *{pred['pT']}*")
            # Csak a legfontosabb 3 threshold
            key_thresholds = ["8.5", "9.5", "10.5"]
            prob_parts = []
            for t in key_thresholds:
                p = pred["probs"].get(t, 0)
                icon = "🟢" if p >= 60 else "🟡" if p >= 40 else "🔴"
                prob_parts.append(f"{icon}{t}: {p}%")
            lines.append("  " + " | ".join(prob_parts))
        else:
            lines.append("  ⚠️ Nincs elegendő adat")
    return "\n".join(lines)

def format_telegram_full(league_sections, today):
    """Teljes napi Telegram üzenet összes ligával."""
    header = [
        "⚽ *Corners Prediction — Napi jelentés*",
        f"📅 {today}",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]
    if not league_sections:
        return "\n".join(header + ["\nMa nincs mérkőzés egyik ligában sem.",
                                    "\n_Daily Corners v1.0 • Csak tájékoztató célra_"])
    parts = header + [""]
    for section in league_sections:
        parts.append(section)
        parts.append("─────────────────────")
    parts.append("\n_Daily Corners v1.0 • Csak tájékoztató célra_")
    return "\n".join(parts)

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"Corner Prophet Napi Becslés v1.0 — {today}")

    hist = load_json(HIST_FILE, [])
    existing_ids = {e["id"] for e in hist}
    league_sections = []
    total_fixtures = 0

    for league_code, league_info in LEAGUES.items():
        print(f"\n── {league_info['name']} ──")
        csv_prefix = league_info["csv_prefix"]
        fdorg_code = league_info["fdorg_code"]

        # Szezon konfig betöltése
        csv_files, season_weights, current_season = load_season_config(csv_prefix)

        # CSV adatok betöltése
        matches = load_matches(csv_files, season_weights)
        print(f"  Meccsek: {len(matches)} | Aktuális szezon: {current_season}")

        if not matches:
            print(f"  Nincs CSV adat, kihagyva")
            continue

        # Aznapi meccsek lekérése
        fixtures = get_fixtures(fdorg_code, today)
        print(f"  Mai meccsek: {len(fixtures)}")

        if not fixtures:
            continue

        total_fixtures += len(fixtures)
        predictions = {}

        for fix in fixtures:
            home_raw = fix["homeTeam"]["shortName"]
            away_raw = fix["awayTeam"]["shortName"]
            entry_id = f"{today}_{league_code}_{home_raw.replace(' ','')}_{away_raw.replace(' ','')}"

            pred = predict(matches, home_raw, away_raw, current_season)
            if pred:
                predictions[f"{home_raw}|{away_raw}"] = pred
                print(f"  {home_raw} vs {away_raw}: {pred['pT']} szöglet")
                if entry_id not in existing_ids:
                    hist.insert(0, {
                        "id": entry_id,
                        "date": today,
                        "league": league_code,
                        "leagueName": league_info["name"],
                        "savedAt": datetime.now(timezone.utc).isoformat(),
                        "home": home_raw, "away": away_raw,
                        "predH": pred["pH"], "predA": pred["pA"], "predT": pred["pT"],
                        "probs": pred["probs"],
                        "actualH": None, "actualA": None, "actualT": None,
                        "error": None,
                        "matchId": fix.get("id")
                    })
            else:
                print(f"  {home_raw} vs {away_raw}: nincs CSV adat")

        # Liga szekció Telegramhoz
        section = format_telegram_league(league_info["name"], fixtures, predictions)
        if section:
            league_sections.append(section)

    # Mentés
    save_json(HIST_FILE, hist)
    update_summary()

    # Telegram
    tg_msg = format_telegram_full(league_sections, today)
    print(f"\nTelegram üzenet ({len(tg_msg)} karakter):")
    print(tg_msg[:300] + "..." if len(tg_msg) > 300 else tg_msg)
    send_telegram(tg_msg)
    print(f"\nKész! {total_fixtures} mérkőzés feldolgozva.")

if __name__ == "__main__":
    main()
