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
from typing import List, Dict, Any, Tuple, Set, Optional

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

# Premier League teams (lowercase)
PREMIER_LEAGUE_TEAMS: Set[str] = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton",
    "chelsea", "crystal palace", "everton", "fulham", "leeds united",
    "liverpool", "manchester city", "manchester united", "newcastle",
    "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton", "wolverhampton wanderers"
}

# Allowed football leagues
ALLOWED_FOOTBALL_LEAGUES: Set[str] = {
    "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "UEFA Euro", "FA Cup", "League Cup", "FIFA World Cup", "International Friendly"
}

# Tennis keywords for detection
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
    """Fetch channel list, return {channelNo: channelName} for 'now Sports' only."""
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
    """Fetch 7-day EPG data."""
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


def clean_brackets(text: str) -> str:
    """Remove anything inside square brackets including brackets themselves."""
    return re.sub(r"\[.*?\]", "", text).strip()


def is_live(title: str) -> bool:
    """Strictly check for [Live] tag (case-insensitive)."""
    return bool(re.search(r"\[Live\]", title, re.IGNORECASE))


def find_premier_league_teams(text: str) -> Tuple[Set[str], bool]:
    """Find PL team names in text. Returns (found_teams, has_two_or_more)."""
    text_lower = text.lower()
    found = set()
    for team in PREMIER_LEAGUE_TEAMS:
        if team in text_lower:
            found.add(team)
    return found, len(found) >= 2


def is_football_league_allowed(text: str) -> bool:
    """Check if text contains any allowed football league."""
    text_lower = text.lower()
    return any(allowed.lower() in text_lower for allowed in ALLOWED_FOOTBALL_LEAGUES)


def is_tennis_event(text: str) -> bool:
    """Check if text contains tennis keywords."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in TENNIS_KEYWORDS)


def extract_league_matchup(raw_title: str) -> Tuple[str, str]:
    """
    Extract League and Matchup from raw title, with special handling for tennis.
    """
    # First remove [Live] and other brackets for cleaner parsing
    cleaned = clean_brackets(raw_title)
    # Also remove trailing "Live" word that may appear without brackets
    cleaned = re.sub(r"\s*Live\s*$", "", cleaned, flags=re.IGNORECASE).strip()

    # Check for tennis pattern: e.g., "WTA 26 Porsche Tennis Grand Prix Final"
    # We want to extract "WTA 26" as league and rest as matchup
    tennis_pattern = re.compile(
        r"^(ATP|WTA)\s+\d{1,4}\b",
        re.IGNORECASE
    )
    tennis_match = tennis_pattern.search(cleaned)
    if tennis_match:
        league_part = tennis_match.group(0)  # e.g., "WTA 26"
        matchup_part = cleaned[tennis_match.end():].strip()
        # If matchup part contains a dash, we can keep structure
        if not matchup_part:
            matchup_part = cleaned  # fallback
        return league_part, matchup_part

    # General split by colon or dash
    parts = re.split(r"\s*[:：\-–]\s*", cleaned, maxsplit=1)
    if len(parts) == 2:
        league = parts[0].strip()
        matchup = parts[1].strip()
        # Further clean: if league contains "Live" word, remove
        league = re.sub(r"\s*Live\b", "", league, flags=re.IGNORECASE).strip()
        matchup = re.sub(r"\s*Live\b", "", matchup, flags=re.IGNORECASE).strip()
        return league, matchup
    else:
        # No clear separator, treat whole as matchup, league unknown
        return "", cleaned


def parse_sports_programs(epg_data: Dict[int, List[List[Dict]]],
                          channel_numbers: List[str],
                          channel_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """Parse raw EPG, apply strict live + league filters."""
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

                # Must contain [Live] tag
                if not is_live(title):
                    continue

                # Pre-check if it's a target sport (football or tennis)
                if not (is_football_league_allowed(title) or is_tennis_event(title)):
                    continue

                # Special Premier League team count check
                if "premier league" in title.lower():
                    _, has_two = find_premier_league_teams(title)
                    if not has_two:
                        continue

                # Extract league and matchup
                league, matchup = extract_league_matchup(title)

                # If league empty but it's tennis, try to derive from title
                if not league and is_tennis_event(title):
                    # Fallback for tennis: use first word (ATP/WTA) as league
                    first_word = title.split()[0]
                    if first_word.upper() in ("ATP", "WTA"):
                        league = first_word.upper()
                        matchup = title[len(first_word):].strip()
                    else:
                        league = "Tennis"
                        matchup = title

                # If still empty, use "Sports"
                if not league:
                    league = "Sports"
                if not matchup:
                    matchup = title

                # Timestamp to Vietnam time
                start_ts = epg_item.get("start", 0) / 1000
                dt_start = datetime.fromtimestamp(start_ts, tz=VIETNAM_TZ)

                events.append({
                    "Date": dt_start.strftime("%Y-%m-%d"),
                    "Time": dt_start.strftime("%H:%M"),
                    "League": league,
                    "Matchup": matchup,
                    "Services": [ch_name],
                    "_raw": title  # for debugging only
                })

    return events


def deduplicate_events(events: List[Dict]) -> List[Dict]:
    """Merge same events on multiple channels."""
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
    print("🚀 Now TV Sports Live Schedule Extractor (Strict Filters)")
    channel_map = fetch_channels()
    if not channel_map:
        print("❌ No 'now Sports' channels found.")
        sys.exit(1)

    channel_numbers = list(channel_map.keys())
    epg_data = fetch_7day_epg(channel_numbers)

    print("🔍 Parsing and filtering live sports events...")
    events = parse_sports_programs(epg_data, channel_numbers, channel_map)

    events = deduplicate_events(events)
    print(f"🎯 Found {len(events)} unique live events matching criteria.")

    events.sort(key=lambda x: (x["Date"], x["Time"]))

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

    print("\n📋 Sample (first 5):")
    for ev in output_events[:5]:
        print(f"{ev['Date']} {ev['Time']} | {ev['League']} | {ev['Matchup']} | {', '.join(ev['Services'])}")


if __name__ == "__main__":
    asyncio.run(main())
