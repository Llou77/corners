#!/usr/bin/env python3
"""
Corner Prophet - Napi Report Generator v0.5
Futtatja a szoglet modellt az aznapi PL meccsekre
football-data.org API alapjan
"""

import json
import urllib.request
import urllib.error
import sys
import os
from datetime import datetime, timezone

FDORG_TOKEN = os.environ.get("FDORG_TOKEN", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_TO = os.environ.get("SMTP_TO", "")

DATA_DIR = "data"
CSV_FILES = {
    "2024/25": f"{DATA_DIR}/E0_2425.csv",
    "2023/24": f"{DATA_DIR}/E0_2324.csv",
    "2022/23": f"{DATA_DIR}/E0_2223.csv",
}
SEASON_W = {"2024/25": 0.6, "2023/24": 0.3, "2022/23": 0.1}

# ── CSV BETÖLTÉS ──────────────────────────────────────────────────────────────

def load_matches():
    all_matches = []
    for season, path in CSV_FILES.items():
        if not os.path.exists(path):
            print(f"WARN: {path} not found, skipping")
            continue
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().strip().split("\n")
        if len(lines) < 2:
            continue
        hdrs = [h.strip() for h in lines[0].split(",")]
        hi = hdrs.index("HomeTeam")
        ai = hdrs.index("AwayTeam")
        hci = hdrs.index("HC")
        aci = hdrs.index("AC")
        di = hdrs.index("Date") if "Date" in hdrs else -1
        for line in lines[1:]:
            v = line.split(",")
            if len(v) <= max(hi, ai, hci, aci):
                continue
            try:
                hc = float(v[hci])
                ac = float(v[aci])
            except ValueError:
                continue
            all_matches.append({
                "home": v[hi].strip(),
                "away": v[ai].strip(),
                "HC": hc,
                "AC": ac,
                "date": v[di].strip() if di >= 0 else "",
                "_s": season,
            })
    return all_matches

# ── FOOTBALL-DATA.ORG API ─────────────────────────────────────────────────────

def get_today_fixtures():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = f"https://api.football-data.org/v4/competitions/PL/matches?dateFrom={today}&dateTo={today}&status=SCHEDULED"
    req = urllib.request.Request(url, headers={"X-Auth-Token": FDORG_TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return data.get("matches", [])
    except Exception as e:
        print(f"API hiba: {e}")
        return []

# ── MODELL (v0.3 logika) ──────────────────────────────────────────────────────

def parse_date(d):
    if not d:
        return 0
    parts = d.split("/")
    if len(parts) == 3:
        dd, mm, yy = parts
        y = (1900 if int(yy) > 50 else 2000) + int(yy) if len(yy) == 2 else int(yy)
        return datetime(y, int(mm), int(dd)).timestamp()
    try:
        return datetime.fromisoformat(d).timestamp()
    except:
        return 0

def sw(m):
    return SEASON_W.get(m["_s"], 0.1)

def get_ms(matches, team, role, w):
    ms = [m for m in matches if (m["home"] if role == "home" else m["away"]) == team]
    ms.sort(key=lambda m: parse_date(m["date"]), reverse=True)
    return ms[:w] if w != "all" else ms

def wavg_combined(matches, val_fn):
    if not matches:
        return 0
    total = ws = 0
    for i, m in enumerate(matches):
        w = sw(m) * (len(matches) - i)
        total += val_fn(m) * w
        ws += w
    return total / ws if ws else 0

def tactic_def_idx(matches, team, role):
    curr = [m for m in matches if m["_s"] == "2024/25" and
            (m["home"] if role == "home" else m["away"]) == team]
    if not curr:
        curr = [m for m in matches if (m["home"] if role == "home" else m["away"]) == team]
    if not curr:
        return 1.0
    conceded = [m["AC"] if role == "home" else m["HC"] for m in curr]
    team_avg = sum(conceded) / len(conceded)
    lg_ms = [m for m in matches if m["_s"] == "2024/25"] or matches
    lg_vals = [m["AC"] if role == "home" else m["HC"] for m in lg_ms]
    lg_avg = sum(lg_vals) / len(lg_vals) if lg_vals else 1
    return team_avg / lg_avg if lg_avg else 1.0

def lg_avgs(matches):
    wH = wA = wS = 0
    for m in matches:
        w = sw(m)
        wH += m["HC"] * w
        wA += m["AC"] * w
        wS += w
    return (wH/wS if wS else 5), (wA/wS if wS else 5)

def poisson_prob(lam, k):
    import math
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam + k * math.log(lam) - sum(math.log(i) for i in range(1, k+1)))

def poisson_over(lH, lA, threshold):
    prob = 0
    for h in range(36):
        for a in range(36):
            if h + a > threshold:
                prob += poisson_prob(lH, h) * poisson_prob(lA, a)
    return min(prob, 1)

def predict(matches, home_team, away_team, win=7):
    hH = get_ms(matches, home_team, "home", win)
    aA = get_ms(matches, away_team, "away", win)
    if not hH or not aA:
        return None
    lgH, lgA = lg_avgs(matches)
    hFor = wavg_combined(hH, lambda m: m["HC"])
    aFor = wavg_combined(aA, lambda m: m["AC"])
    hAtk = hFor / lgH if lgH else 1
    aAtk = aFor / lgA if lgA else 1
    hDefIdx = tactic_def_idx(matches, home_team, "home")
    aDefIdx = tactic_def_idx(matches, away_team, "away")
    pH = round(lgH * hAtk * aDefIdx, 2)
    pA = round(lgA * aAtk * hDefIdx, 2)
    pT = round(pH + pA, 2)
    thresholds = [6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5]
    probs = {t: round(poisson_over(pH, pA, t) * 100, 1) for t in thresholds}
    return {"pH": pH, "pA": pA, "pT": pT, "probs": probs,
            "hAtk": round(hAtk, 3), "aAtk": round(aAtk, 3),
            "hDef": round(hDefIdx, 3), "aDef": round(aDefIdx, 3),
            "lgAvg": round(lgH + lgA, 1)}

# ── REPORT FORMÁZÁS ───────────────────────────────────────────────────────────

def format_telegram(fixtures, predictions, today):
    lines = [
        f"⚽ *Corner Prophet — Napi Report*",
        f"📅 {today} | Premier League",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]
    if not fixtures:
        lines.append("\nMa nincs Premier League mérkőzés.")
        return "\n".join(lines)

    for fix in fixtures:
        home = fix["homeTeam"]["shortName"]
        away = fix["awayTeam"]["shortName"]
        time = fix["utcDate"][11:16]
        pred = predictions.get(f"{home}|{away}")
        lines.append(f"\n🕐 {time} UTC | *{home} vs {away}*")
        if pred:
            lines.append(f"📐 Várható szögletek: {pred['pH']} + {pred['pA']} = *{pred['pT']}*")
            lines.append(f"📊 Liga átlag: {pred['lgAvg']}")
            lines.append("📈 Poisson valószínűségek:")
            for t, p in pred["probs"].items():
                under = round(100 - p, 1)
                bar = "🟢" if p >= 60 else "🟡" if p >= 40 else "🔴"
                lines.append(f"  {bar} Felett {t}: *{p}%* / Alatt: {under}%")
        else:
            lines.append("  ⚠️ Nincs elegendő adat az előrejelzéshez")
        lines.append("─────────────────────")

    lines.append("\n_Corner Prophet v0.3 • Csak tájékoztató célra_")
    return "\n".join(lines)

def format_email_html(fixtures, predictions, today):
    rows = ""
    if not fixtures:
        rows = "<p>Ma nincs Premier League mérkőzés.</p>"
    else:
        for fix in fixtures:
            home = fix["homeTeam"]["shortName"]
            away = fix["awayTeam"]["shortName"]
            time = fix["utcDate"][11:16]
            pred = predictions.get(f"{home}|{away}")
            rows += f"""
            <div style="background:#10141c;border:1px solid #1e2736;padding:16px;margin:12px 0;border-radius:4px">
              <div style="color:#8892a4;font-size:12px;margin-bottom:6px">{time} UTC</div>
              <div style="color:#e8eaf0;font-size:18px;font-weight:bold;margin-bottom:10px">{home} vs {away}</div>
            """
            if pred:
                rows += f"""
              <div style="display:flex;gap:20px;margin-bottom:10px">
                <div style="text-align:center">
                  <div style="color:#5a6478;font-size:11px">HAZAI</div>
                  <div style="color:#00e5ff;font-size:32px;font-weight:900">{pred["pH"]}</div>
                </div>
                <div style="text-align:center">
                  <div style="color:#5a6478;font-size:11px">ÖSSZ</div>
                  <div style="color:#a8ff3e;font-size:32px;font-weight:900">{pred["pT"]}</div>
                </div>
                <div style="text-align:center">
                  <div style="color:#5a6478;font-size:11px">VENDÉG</div>
                  <div style="color:#ff6b35;font-size:32px;font-weight:900">{pred["pA"]}</div>
                </div>
              </div>
              <table style="width:100%;border-collapse:collapse;font-size:12px">
                <tr style="color:#5a6478">
                  <td>Határ</td><td>Felett %</td><td>Alatt %</td>
                </tr>
                """
                for t, p in pred["probs"].items():
                    under = round(100 - p, 1)
                    color = "#a8ff3e" if p >= 60 else "#00e5ff" if p >= 40 else "#ff6b35"
                    rows += f"""<tr style="color:#e8eaf0;border-top:1px solid #1e2736">
                  <td style="padding:3px 0">{t}</td>
                  <td style="color:{color};font-weight:bold">{p}%</td>
                  <td style="color:#8892a4">{under}%</td>
                </tr>"""
                rows += "</table>"
            else:
                rows += '<div style="color:#ff6b35">⚠️ Nincs elegendő adat</div>'
            rows += "</div>"

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="background:#0a0c10;color:#e8eaf0;font-family:monospace;padding:20px;max-width:600px">
  <div style="border-bottom:1px solid #1e2736;padding-bottom:16px;margin-bottom:20px">
    <h1 style="color:#00e5ff;font-size:24px;margin:0">⚽ Corner Prophet</h1>
    <div style="color:#5a6478;font-size:12px">Napi Report • {today} • Premier League</div>
  </div>
  {rows}
  <div style="border-top:1px solid #1e2736;padding-top:12px;margin-top:20px;color:#5a6478;font-size:11px">
    Corner Prophet v0.3 • Csak tájékoztató célra • Nem fogadási tanács
  </div>
</body></html>"""

# ── KÜLDÉS ────────────────────────────────────────────────────────────────────

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("WARN: Telegram credentials missing, skipping")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(f"Telegram: {resp.status}")

def send_email(subject, html_body):
    if not SMTP_USER or not SMTP_PASS or not SMTP_TO:
        print("WARN: Email credentials missing, skipping")
        return
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = SMTP_TO
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP("smtp-mail.outlook.com", 587) as s:
        s.ehlo()
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, SMTP_TO, msg.as_string())
    print("Email: sent")

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"Corner Prophet Napi Report — {today}")

    # Betöltés
    matches = load_matches()
    print(f"Betöltött meccsek: {len(matches)}")

    # Aznapi fixtures
    fixtures = get_today_fixtures()
    print(f"Mai PL meccsek: {len(fixtures)}")

    # Előrejelzések
    predictions = {}
    # Csapatnév mapping: football-data.org shortName -> CSV név
    name_map = {
        "Arsenal": "Arsenal", "Chelsea": "Chelsea", "Liverpool": "Liverpool",
        "Man United": "Man United", "Man City": "Man City", "Tottenham": "Tottenham",
        "Newcastle": "Newcastle", "Aston Villa": "Aston Villa", "Brighton": "Brighton",
        "West Ham": "West Ham", "Brentford": "Brentford", "Fulham": "Fulham",
        "Crystal Palace": "Crystal Palace", "Everton": "Everton", "Wolves": "Wolves",
        "Bournemouth": "Bournemouth", "Nott'm Forest": "Nott'm Forest",
        "Leicester": "Leicester", "Ipswich": "Ipswich", "Southampton": "Southampton",
        "Leeds": "Leeds", "Burnley": "Burnley", "Luton": "Luton",
        "Sheffield United": "Sheffield United",
    }

    for fix in fixtures:
        home_raw = fix["homeTeam"]["shortName"]
        away_raw = fix["awayTeam"]["shortName"]
        home = name_map.get(home_raw, home_raw)
        away = name_map.get(away_raw, away_raw)
        pred = predict(matches, home, away)
        if pred:
            predictions[f"{home_raw}|{away_raw}"] = pred
            print(f"  {home} vs {away}: {pred['pT']} szöglet")
        else:
            print(f"  {home} vs {away}: nincs adat")

    # Formázás
    tg_text = format_telegram(fixtures, predictions, today)
    email_html = format_email_html(fixtures, predictions, today)
    subject = f"Corner Prophet — {today} — {len(fixtures)} PL meccs"

    # Küldés
    send_telegram(tg_text)
    send_email(subject, email_html)
    print("Kész!")

if __name__ == "__main__":
    main()
