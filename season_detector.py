#!/usr/bin/env python3
"""
Corner Prophet - Multi-Liga Szezon Detektor v1.0
Minden ligához meghatározza az aktuális 3 szezont.
Kimenet: data/season_config_E0.json, data/season_config_F1.json, stb.
"""

import json, urllib.request, os
from datetime import datetime, timezone

TIME_FACTORS = [1.0, 0.6, 0.3]

LEAGUES = {
    "E0":  "Premier League",
    "F1":  "Ligue 1",
    "SP1": "La Liga",
    "D1":  "Bundesliga",
    "I1":  "Serie A",
}

def check_season(season_code, league_prefix):
    url = f"https://www.football-data.co.uk/mmz4281/{season_code}/{league_prefix}.csv"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            lines = [l for l in r.read().decode("utf-8", errors="ignore").strip().split("\n") if l.strip()]
            return max(0, len(lines) - 1)
    except:
        return 0

def get_season_code(year_start):
    return str(year_start)[-2:] + str(year_start + 1)[-2:]

def calc_weights(seasons):
    raw = {}
    for i, s in enumerate(seasons):
        tf = TIME_FACTORS[i] if i < len(TIME_FACTORS) else 0.1
        raw[s["label"]] = s["matches"] * tf
    total = sum(raw.values())
    if not total:
        return {s["label"]: round(1/len(seasons), 4) for s in seasons}
    return {label: round(val/total, 4) for label, val in raw.items()}

def detect_league(league_prefix, league_name):
    now = datetime.now(timezone.utc)
    latest_start = now.year if now.month >= 8 else now.year - 1

    print(f"\n  {league_name} ({league_prefix}):")
    seasons = []
    for start in range(latest_start, latest_start - 4, -1):
        code = get_season_code(start)
        label = f"{start}/{start+1}"
        matches = check_season(code, league_prefix)
        print(f"    {label}: {matches} meccs")
        if matches > 0:
            seasons.append({
                "label": label,
                "code": code,
                "file": f"data/{league_prefix}_{code}.csv",
                "matches": matches
            })
        if len(seasons) == 3:
            break

    if not seasons:
        print(f"    HIBA: Nincs elérhető adat!")
        return None

    weights = calc_weights(seasons)
    for s in seasons:
        s["weight"] = weights[s["label"]]

    config = {
        "league": league_prefix,
        "leagueName": league_name,
        "seasons": seasons,
        "weights": weights,
        "current": seasons[0]["label"],
        "updatedAt": now.isoformat(),
        "weightingMethod": "match_count_x_time_factor (1.0/0.6/0.3)"
    }

    weights_str = [(s['label'], str(round(s['weight']*100, 1)) + '%') for s in seasons]
    print(f"    Súlyok: {weights_str}")
    return config

def main():
    now = datetime.now(timezone.utc)
    print(f"Corner Prophet Szezon Detektor v1.0 — {now.strftime('%Y-%m-%d')}")

    os.makedirs("data", exist_ok=True)
    all_configs = {}

    for prefix, name in LEAGUES.items():
        config = detect_league(prefix, name)
        if config:
            # Liga-specifikus konfig
            out_path = f"data/season_config_{prefix}.json"
            with open(out_path, "w") as f:
                json.dump(config, f, indent=2)
            all_configs[prefix] = config

            # PL-hoz felülírjuk az alap season_config.json-t is (visszafelé kompatibilitás)
            if prefix == "E0":
                with open("data/season_config.json", "w") as f:
                    json.dump(config, f, indent=2)

    # Összesített konfig
    summary = {
        "leagues": list(all_configs.keys()),
        "updatedAt": now.isoformat()
    }
    with open("data/leagues_config.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nKész! {len(all_configs)} liga konfigurálva.")

if __name__ == "__main__":
    main()
