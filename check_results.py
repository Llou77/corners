#!/usr/bin/env python3
"""
Corner Prophet - Eredmény Ellenőrző v0.5
Fut: minden nap 04:00 UTC (06:00 Budapest)
1. Lekéri a tegnapi PL meccsek tényleges szögletszámait
2. Beírja a predictions/history.json-ba
3. Frissíti a predictions/summary.json-t
"""

import json, urllib.request, os, math
from datetime import datetime, timezone, timedelta

FDORG_TOKEN = os.environ.get("FDORG_TOKEN", "")

PRED_DIR  = "predictions"
HIST_FILE = f"{PRED_DIR}/history.json"
SUM_FILE  = f"{PRED_DIR}/summary.json"
SEASON_W  = {"2024/25": 0.6, "2023/24": 0.3, "2022/23": 0.1}

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
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def get_finished_matches(date):
    url = f"https://api.football-data.org/v4/competitions/PL/matches?dateFrom={date}&dateTo={date}&status=FINISHED"
    try:
        return api_get(url).get("matches", [])
    except Exception as e:
        print(f"API hiba: {e}"); return []

def update_summary(hist):
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
    save_json(SUM_FILE, {
        "evaluated": n, "mae": mae, "bias": bias, "acc": acc,
        "updatedAt": datetime.now(timezone.utc).isoformat()
    })
    print(f"Summary frissítve: n={n}, MAE={mae}, bias={bias}")
    if acc.get("9.5"):
        print(f"  9.5 találati arány: {acc['9.5']}%")

def main():
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Eredmény ellenőrzés — {yesterday}")

    finished = get_finished_matches(yesterday)
    print(f"Befejezett meccsek: {len(finished)}")
    if not finished:
        print("Nincs tegnapi meccs."); return

    hist = load_json(HIST_FILE, [])
    updated = 0

    for match in finished:
        home_raw = match["homeTeam"]["shortName"]
        away_raw = match["awayTeam"]["shortName"]
        entry_id = f"{yesterday}_{home_raw.replace(' ','')}_{away_raw.replace(' ','')}"

        # Szöglet adatok a football-data.org-tól
        stats = match.get("statistics", []) or []
        hc = ac = None
        for s in stats:
            if s.get("type") == "CORNER_KICKS":
                hc = s.get("home")
                ac = s.get("away")
                break

        # Ha nincs stat a match objectben, próbáljuk a score-ból
        # football-data.org v4-ben a corners a statistics arrayban van
        if hc is None:
            # Lekérjük a meccs részleteit
            try:
                match_detail = api_get(f"https://api.football-data.org/v4/matches/{match['id']}")
                for s in match_detail.get("statistics", []) or []:
                    if s.get("type") == "CORNER_KICKS":
                        hc = s.get("home")
                        ac = s.get("away")
                        break
            except:
                pass

        # Keressük a history-ban
        found = False
        for entry in hist:
            if entry["id"] == entry_id and entry.get("actualT") is None:
                if hc is not None and ac is not None:
                    entry["actualH"] = int(hc)
                    entry["actualA"] = int(ac)
                    entry["actualT"] = int(hc) + int(ac)
                    entry["error"]   = round(entry["predT"] - entry["actualT"], 2)
                    entry["checkedAt"] = datetime.now(timezone.utc).isoformat()
                    print(f"  ✓ {home_raw} vs {away_raw}: {hc}+{ac}={int(hc)+int(ac)} (becsült: {entry['predT']}, hiba: {entry['error']})")
                    updated += 1
                else:
                    print(f"  ⚠ {home_raw} vs {away_raw}: nincs szöglet adat az API-ban")
                found = True
                break
        if not found:
            print(f"  – {home_raw} vs {away_raw}: nem volt tegnapi becslés")

    if updated > 0:
        save_json(HIST_FILE, hist)
        update_summary(hist)
        print(f"{updated} eredmény frissítve.")
    else:
        print("Nincs frissítendő adat.")

if __name__ == "__main__":
    main()
