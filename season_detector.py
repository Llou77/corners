#!/usr/bin/env python3
"""
Corner Prophet - Automatikus szezon-detektor
Meghatározza az aktuális 3 szezont és elmenti season_config.json-ba
Súlyozás: meccsszám-arányos + időbeli leértékelés (1.0 / 0.6 / 0.3)
"""

import json, urllib.request, os
from datetime import datetime, timezone

# Időbeli leértékelési faktorok (legfrissebb szezon = 1.0)
TIME_FACTORS = [1.0, 0.6, 0.3]

def check_season(season_code):
    url = f"https://www.football-data.co.uk/mmz4281/{season_code}/E0.csv"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            lines = [l for l in r.read().decode("utf-8", errors="ignore").strip().split("\n") if l.strip()]
            return max(0, len(lines) - 1)
    except:
        return 0

def get_season_code(year_start):
    return str(year_start)[-2:] + str(year_start + 1)[-2:]

def calc_weights(seasons):
    """
    Meccsszam-aranyos + idöbeli leertekeles kombinalt sulyozas.
    seasons: list of dicts with 'matches' field, ordered newest first
    """
    raw = {}
    for i, s in enumerate(seasons):
        tf = TIME_FACTORS[i] if i < len(TIME_FACTORS) else 0.1
        raw[s["label"]] = s["matches"] * tf
    
    total = sum(raw.values())
    if total == 0:
        return {s["label"]: round(1/len(seasons), 4) for s in seasons}
    
    return {label: round(val/total, 4) for label, val in raw.items()}

def main():
    now = datetime.now(timezone.utc)
    latest_start = now.year if now.month >= 8 else now.year - 1
    
    print(f"Szezon-detektor: {now.strftime('%Y-%m-%d')}")
    
    seasons = []
    for start in range(latest_start, latest_start - 4, -1):
        code = get_season_code(start)
        label = f"{start}/{start+1}"
        matches = check_season(code)
        print(f"  {label}: {matches} meccs")
        if matches > 0:
            seasons.append({
                "label": label,
                "code": code,
                "file": f"data/E0_{code}.csv",
                "matches": matches
            })
        if len(seasons) == 3:
            break
    
    if not seasons:
        print("HIBA: Egy szezon sem elérhető!"); return
    
    # Adaptív súlyok kiszámítása
    weights = calc_weights(seasons)
    for s in seasons:
        s["weight"] = weights[s["label"]]
    
    config = {
        "seasons": seasons,
        "weights": weights,
        "current": seasons[0]["label"],
        "updatedAt": now.isoformat(),
        "weightingMethod": "match_count_x_time_factor (1.0/0.6/0.3)"
    }
    
    os.makedirs("data", exist_ok=True)
    with open("data/season_config.json", "w") as f:
        json.dump(config, f, indent=2)
    
    print(f"\nSúlyok:")
    for s in seasons:
        print(f"  {s['label']}: {s['weight']*100:.1f}% ({s['matches']} meccs × {TIME_FACTORS[seasons.index(s)]})")

if __name__ == "__main__":
    main()
