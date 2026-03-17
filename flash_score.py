import requests
import json
from datetime import datetime, timezone
import pytz

VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")

# =========================
# CONFIG FILTER
# =========================

EPL_TEAMS = {
    "arsenal","aston villa","bournemouth","brentford","brighton",
    "chelsea","crystal palace","everton","fulham","leeds united",
    "liverpool","manchester city","manchester united","newcastle",
    "nottingham forest","sunderland","tottenham hotspur",
    "west ham united","wolverhampton"
}

SERIEA_TEAMS = {
    "inter","ac milan","napoli","juventus","roma","atalanta","lazio"
}

LALIGA_TEAMS = {"barcelona","real madrid","atlético"}

BUNDES_TEAMS = {"bayern","dortmund","leverkusen"}

LIGUE1_TEAMS = {"psg","marseille"}

# =========================
# FETCH MATCH LIST
# =========================

def fetch_matches(date_str, sport_id):
    url = f"https://d.flashscore.com/x/feed/f_{sport_id}_{date_str}"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers)
    return r.text.split("\n")

# =========================
# FETCH TV
# =========================

def fetch_tv(match_id):
    url = f"https://d.flashscore.com/x/feed/tv_{match_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=5)
        lines = r.text.split("\n")

        tv_data = []
        for l in lines:
            if "|" in l:
                parts = l.split("|")
                if len(parts) > 2:
                    country = parts[1]
                    channels = parts[2].split(",")
                    tv_data.append({
                        "country": country,
                        "channels": channels
                    })
        return tv_data
    except:
        return []

# =========================
# FILTER MATCH
# =========================

def match_valid(league, match):
    m = match.lower()
    l = league.lower()

    if "premier league" in l:
        return any(t in m for t in EPL_TEAMS)

    if "serie a" in l:
        return any(t in m for t in SERIEA_TEAMS)

    if "laliga" in l:
        return any(t in m for t in LALIGA_TEAMS)

    if "bundesliga" in l:
        return any(t in m for t in BUNDES_TEAMS)

    if "ligue 1" in l:
        return any(t in m for t in LIGUE1_TEAMS)

    if "champions league" in l:
        return True

    if "europa league" in l:
        return True

    if "conference league" in l:
        return True

    if "atp" in l or "wta" in l or "grand slam" in l:
        return True

    return False

# =========================
# PARSE MATCH
# =========================

def parse_match(line):
    parts = line.split("|")

    try:
        match_id = parts[0]
        league = parts[1]
        match = parts[2]
        ts = int(parts[3])

        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        vn_time = dt.astimezone(VN_TZ)

        return {
            "id": match_id,
            "league": league,
            "match": match,
            "time": vn_time.strftime("%d/%m %I:%M %p"),
            "kick_utc": ts
        }
    except:
        return None

# =========================
# MAIN
# =========================

def main():
    today = datetime.now().strftime("%Y%m%d")

    all_lines = []
    all_lines += fetch_matches(today, 1)  # football
    all_lines += fetch_matches(today, 2)  # tennis

    games = []

    for line in all_lines:
        if "|" not in line:
            continue

        data = parse_match(line)
        if not data:
            continue

        if not match_valid(data["league"], data["match"]):
            continue

        tv = fetch_tv(data["id"])

        games.append({
            "league": data["league"],
            "time": data["time"],
            "match": data["match"],
            "kick_utc": data["kick_utc"],
            "tv_channels": tv
        })

    output = {
        "updated": datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M VN"),
        "days": {
            today: {
                "date": datetime.now().strftime("%A, %d/%m"),
                "games": games
            }
        }
    }

    with open("flashscore.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(games)} matches")


if __name__ == "__main__":
    main()
