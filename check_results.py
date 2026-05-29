#!/usr/bin/env python3
"""
Corner Prophet - Eredmény Ellenőrző v1.0
Multi-liga: PL, Ligue 1, La Liga, Bundesliga, Serie A
Fut: minden nap 04:00 UTC
"""

import json, urllib.request, os, math
from datetime import datetime, timezone, timedelta

FDORG_TOKEN = os.environ.get("FDORG_TOKEN", "")

PRED_DIR  = "predictions"
HIST_FILE = f"{PRED_DIR}/history.json"
SUM_FILE  = f"{PRED_DIR}/summary.json"

LEAGUES = {
    "PL":  "PL",
    "FL1": "FL1",
    "PD":  "PD",
    "BL1": "BL1",
    "SA":  "SA",
}

TIME_FACTORS = [1.0, 0.6, 0.3]

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except: return default

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def api_get(url):
    req = urllib.request.Request(url, headers={"X-Auth-Token": FDORG_TOKEN})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def get_finished_matches(fdorg_code, date):
    url = f"https://api.football-data.org/v4/competitions/{fdorg_code}/matches?dateFrom={date}&dateTo={date}&status=FINISHED"
    try:
        return api_get(url).get("matches", [])
    except Exception as e:
        print(f"  {fdorg_code} API hiba: {e}"); return []

def get_match_corners(match):
    """Kinyeri a szögletszámokat egy meccs objektumból."""
    # football-data.org v4: statistics tömbben
    stats = match.get("statistics", []) or []
    hc = ac = None
    for s in stats:
        if s.get("type") == "CORNER_KICKS":
            hc = s.get("home")
            ac = s.get("away")
            break

    # Ha nincs a match objectben, próbáljuk a match detail endpoint-ot
    if hc is None and match.get("id"):
        try:
            detail = api_get(f"https://api.football-data.org/v4/matches/{match['id']}")
            for s in (detail.get("statistics", []) or []):
                if s.get("type") == "CORNER_KICKS":
                    hc = s.get("home")
                    ac = s.get("away")
                    break
        except:
            pass

    return hc, ac

def update_summary(hist):
    done = [e for e in hist if e.get("actualT") is not None]
    if not done:
        save_json(SUM_FILE, {"evaluated": 0, "mae": None, "bias": None, "acc": {}, "calibration": {}})
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

    # Kalibrációs faktor ligánként
    cal = {}
    for t in ["8.5", "9.5", "10.5"]:
        rel = [e for e in done if e.get("probs") and t in e["probs"]]
        if len(rel) >= 5:
            pred_probs = [e["probs"][t]/100 for e in rel]
            actual_over = [1 if e["actualT"] > float(t) else 0 for e in rel]
            avg_pred = sum(pred_probs)/len(pred_probs)
            avg_actual = sum(actual_over)/len(actual_over)
            cal[t] = round(avg_actual - avg_pred, 3)

    # Liga-szintű statisztikák
    league_stats = {}
    for league in set(e.get("league","PL") for e in done):
        lg_done = [e for e in done if e.get("league","PL") == league]
        if not lg_done: continue
        lg_errors = [e["predT"] - e["actualT"] for e in lg_done]
        league_stats[league] = {
            "n": len(lg_done),
            "mae": round(sum(abs(x) for x in lg_errors) / len(lg_done), 3),
            "bias": round(sum(lg_errors) / len(lg_done), 3)
        }

    save_json(SUM_FILE, {
        "evaluated": n, "mae": mae, "bias": bias,
        "acc": acc, "calibration": cal,
        "by_league": league_stats,
        "updatedAt": datetime.now(timezone.utc).isoformat()
    })
    print(f"Summary: n={n}, MAE={mae}, bias={bias}")
    for league, stats in league_stats.items():
        print(f"  {league}: n={stats['n']}, MAE={stats['mae']}, bias={stats['bias']}")

def main():
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Eredmény ellenőrzés v1.0 — {yesterday}")

    hist = load_json(HIST_FILE, [])
    total_updated = 0

    for league_code, fdorg_code in LEAGUES.items():
        finished = get_finished_matches(fdorg_code, yesterday)
        if not finished:
            continue
        print(f"\n{league_code}: {len(finished)} befejezett meccs")

        for match in finished:
            home_raw = match["homeTeam"]["shortName"]
            away_raw = match["awayTeam"]["shortName"]

            # Keressük a history-ban (league prefix-szel és anélkül is)
            entry_id_new = f"{yesterday}_{league_code}_{home_raw.replace(' ','')}_{away_raw.replace(' ','')}"
            entry_id_old = f"{yesterday}_{home_raw.replace(' ','')}_{away_raw.replace(' ','')}"

            found = False
            for entry in hist:
                if entry["id"] in (entry_id_new, entry_id_old) and entry.get("actualT") is None:
                    hc, ac = get_match_corners(match)
                    if hc is not None and ac is not None:
                        entry["actualH"] = int(hc)
                        entry["actualA"] = int(ac)
                        entry["actualT"] = int(hc) + int(ac)
                        entry["error"]   = round(entry["predT"] - entry["actualT"], 2)
                        entry["checkedAt"] = datetime.now(timezone.utc).isoformat()
                        print(f"  ✓ {home_raw} vs {away_raw}: {hc}+{ac}={entry['actualT']} (becsült: {entry['predT']}, hiba: {entry['error']})")
                        total_updated += 1
                    else:
                        print(f"  ⚠ {home_raw} vs {away_raw}: nincs szöglet adat")
                    found = True
                    break

            if not found:
                print(f"  – {home_raw} vs {away_raw}: nem volt tegnapi becslés")

    if total_updated > 0:
        save_json(HIST_FILE, hist)
        update_summary(hist)
        print(f"\n{total_updated} eredmény frissítve.")
    else:
        print("\nNincs frissítendő adat.")

if __name__ == "__main__":
    main()
