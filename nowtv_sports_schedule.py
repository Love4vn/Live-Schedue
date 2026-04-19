#!/usr/bin/env python3
"""
Now TV Sports Live Schedule Extractor (English - Vietnam Time)
Fetches EPG from Now TV, filters only "now Sports" channels,
extracts football/tennis live events, and outputs cleaned JSON.
"""

import asyncio
import json
import re
import sys
from datetime import datetime
from typing import List, Dict, Any, Tuple, Set

import pytz
import requests
from bs4 import BeautifulSoup

# ========== CONFIGURATION ==========
BASE_URL = "https://nowplayer.now.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Only channels whose name starts with "now Sports" (case-insensitive)
CHANNEL_NAME_FILTER = "now Sports"

# Vietnam timezone (UTC+7)
VIETNAM_TZ = pytz.timezone("Asia/Ho_Chi_Minh")

# Premier League teams (lowercase for matching)
PREMIER_LEAGUE_TEAMS: Set[str] = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton",
    "chelsea", "crystal palace", "everton", "fulham", "leeds united",
    "liverpool", "manchester city", "manchester united", "newcastle",
    "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton", "wolverhampton wanderers"
}

# Allowed football leagues (exact or partial match)
ALLOWED_FOOTBALL_LEAGUES: Set[str] = {
    "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "UEFA Euro", "FA Cup", "League Cup", "FIFA World Cup", "International Friendly"
}

# Tennis keywords (case-insensitive)
TENNIS_KEYWORDS: Set[str] = {
    "atp", "wta", "atp tour", "wta tour", "atp world tour",
    "grand slam", "australian open", "roland garros", "french open",
    "wimbledon", "us open", "nitto atp finals",
    "atp masters", "atp 1000", "atp 500", "atp 250",
    "wta 1000", "wta 500", "wta 250",
    "davis cup", "billie jean king cup", "laver cup"
}
# ===================================

# ---------- Helper Functions ----------
def fetch_channels() -> Dict[str, str]:
    """Fetch channel list and return mapping {channelNo: channelName} for 'now Sports' only."""
    print("📡 Fetching channel list (English mode)...")
    url = f"{BASE_URL}/channels"
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en,zh;q=0.9"}
    resp = requests.get(url, headers=headers, cookies={"LANG": "en"})
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    channel_map = {}

    for item in soup.find_all("div", class_="product-item"):
        name_tag = item.find("p", class_="img-name")
        channel_tag = item.find("p", class_="channel")
        if name_tag and channel_tag:
            name = name_tag.text.strip()
            ch_no = channel_tag.text.replace("CH", "").strip()
            if name.lower().startswith(CHANNEL_NAME_FILTER.lower()):
                channel_map[ch_no] = name

    print(f"✅ Found {len(channel_map)} 'now Sports' channels.")
    return channel_map


def fetch_7day_epg(channel_numbers: List[str]) -> Dict[int, List[List[Dict]]]:
    """Fetch 7-day EPG data for given channel numbers."""
    print("📡 Fetching 7-day EPG data...")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/plain, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": f"{BASE_URL}/tvguide",
        "X-Requested-With": "XMLHttpRequest",
    }
    cookies = {"LANG": "en"}

    epg_data = {}
    for day in range(1, 8):
        params = [("channelIdList[]", ch) for ch in channel_numbers] + [("day", str(day))]
        try:
            resp = requests.get(
                f"{BASE_URL}/tvguide/epglist",
                headers=headers,
                cookies=cookies,
                params=params,
                timeout=10
            )
            resp.raise_for_status()
            epg_data[day] = resp.json()
            print(f"  Day {day}: OK")
        except Exception as e:
            print(f"  Day {day}: Failed - {e}")
            epg_data[day] = []
    return epg_data


def clean_text(text: str) -> str:
    """Remove tags like [4K], [Live], etc. and trim."""
    # Remove brackets with content e.g. [4K], [Live]
    cleaned = re.sub(r"\[.*?\]", "", text)
    # Remove trailing "Live" word
    cleaned = re.sub(r"\s*[-–]?\s*LIVE\s*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def is_live(title: str) -> bool:
    """Check if title indicates live broadcast."""
    return bool(re.search(r"\[Live\]|LIVE", title, re.IGNORECASE))


def extract_league_matchup(title: str) -> Tuple[str, str]:
    """
    Parse English title into (raw_league, raw_matchup) before cleaning.
    Expects patterns like "Premier League: Arsenal vs Liverpool" or
    "WTA Tour - Match name".
    """
    # Split on common separators
    parts = re.split(r"\s*[:：\-–]\s*", title, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    else:
        return "", title.strip()


def find_premier_league_teams(text: str) -> Tuple[Set[str], bool]:
    """
    Find Premier League team names in text.
    Returns (set of found teams, True if at least two different teams found).
    """
    text_lower = text.lower()
    found_teams = set()
    for team in PREMIER_LEAGUE_TEAMS:
        if team in text_lower:
            found_teams.add(team)
    return found_teams, len(found_teams) >= 2


def is_football_league_allowed(league_name: str) -> bool:
    """Check if league_name contains any allowed football league."""
    league_lower = league_name.lower()
    for allowed in ALLOWED_FOOTBALL_LEAGUES:
        if allowed.lower() in league_lower:
            return True
    return False


def is_tennis_event(title: str) -> bool:
    """Check if title contains any tennis keyword."""
    title_lower = title.lower()
    return any(kw in title_lower for kw in TENNIS_KEYWORDS)


def parse_sports_programs(epg_data: Dict[int, List[List[Dict]]],
                          channel_numbers: List[str],
                          channel_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """
    Parse raw EPG data, apply strict filters, and return cleaned events.
    """
    events = []

    for day in range(1, 8):
        day_progs = epg_data.get(day, [])
        for idx, channel_progs in enumerate(day_progs):
            if idx >= len(channel_numbers):
                continue
            ch_no = channel_numbers[idx]
            ch_name = channel_map.get(ch_no, f"Channel {ch_no}")

            for epg_item in channel_progs:
                title = epg_item.get("name", "").strip()
                if not title:
                    continue

                # Must be live
                if not is_live(title):
                    continue

                # Parse league and matchup parts
                raw_league, raw_matchup = extract_league_matchup(title)

                # Clean them (remove [4K], [Live], etc.)
                league_clean = clean_text(raw_league)
                matchup_clean = clean_text(raw_matchup)

                # Determine sport and apply filters
                # Football check
                if is_football_league_allowed(league_clean) or is_football_league_allowed(title):
                    # Special case: Premier League must contain two known teams
                    if "premier league" in league_clean.lower() or "premier league" in title.lower():
                        _, has_two_teams = find_premier_league_teams(title)
                        if not has_two_teams:
                            continue  # Skip if not enough team names

                    # For other football leagues, we accept (maybe also check for "vs")
                    pass

                elif is_tennis_event(title):
                    # Tennis event - accepted
                    pass
                else:
                    # Not a target sport
                    continue

                # Timestamp conversion to Vietnam time
                start_ts = epg_item.get("start", 0) / 1000
                dt_start = datetime.fromtimestamp(start_ts, tz=VIETNAM_TZ)

                events.append({
                    "Date": dt_start.strftime("%Y-%m-%d"),
                    "Time": dt_start.strftime("%H:%M"),
                    "League": league_clean if league_clean else "Sports",
                    "Matchup": matchup_clean if matchup_clean else title,
                    "Services": [ch_name],
                    # Metadata for debugging (will be removed later)
                    "_raw_title": title,
                    "_channel_no": ch_no
                })

    return events


def deduplicate_events(events: List[Dict]) -> List[Dict]:
    """Merge identical events across multiple channels."""
    merged = {}
    for ev in events:
        key = (ev["Date"], ev["Time"], ev["League"], ev["Matchup"])
        if key not in merged:
            merged[key] = ev.copy()
            merged[key]["Services"] = list(set(ev["Services"]))
        else:
            merged[key]["Services"].extend(ev["Services"])
            merged[key]["Services"] = list(set(merged[key]["Services"]))
    return list(merged.values())


# ---------- Main ----------
async def main():
    print("🚀 Now TV Sports Schedule Extractor (Strict Filters)")
    # 1. Get channels
    channel_map = fetch_channels()
    if not channel_map:
        print("❌ No 'now Sports' channels found.")
        sys.exit(1)

    channel_numbers = list(channel_map.keys())

    # 2. Fetch EPG
    epg_data = fetch_7day_epg(channel_numbers)

    # 3. Parse with strict rules
    print("🔍 Parsing and filtering live sports events...")
    events = parse_sports_programs(epg_data, channel_numbers, channel_map)

    # 4. Deduplicate
    events = deduplicate_events(events)
    print(f"🎯 Found {len(events)} unique live events matching criteria.")

    # 5. Sort
    events.sort(key=lambda x: (x["Date"], x["Time"]))

    # 6. Final output (only required fields)
    output_events = []
    for ev in events:
        output_events.append({
            "Date": ev["Date"],
            "Time": ev["Time"],
            "League": ev["League"],
            "Matchup": ev["Matchup"],
            "Services": ev["Services"]
        })

    output_file = "nowtv_sports_schedule_en.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_events, f, ensure_ascii=False, indent=2)
    print(f"💾 Schedule saved to {output_file}")

    # Print sample
    print("\n📋 Sample (first 5):")
    for ev in output_events[:5]:
        print(f"{ev['Date']} {ev['Time']} | {ev['League']} | {ev['Matchup']} | {', '.join(ev['Services'])}")


if __name__ == "__main__":
    asyncio.run(main())
