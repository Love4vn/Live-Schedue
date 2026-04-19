#!/usr/bin/env python3
"""
Now TV Sports Live Schedule Extractor (English - Vietnam Time)
Fetches EPG from Now TV, filters only "now Sports" channels,
extracts football/tennis events, and outputs JSON in English.
"""

import asyncio
import json
import re
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional

import pytz
import requests
from bs4 import BeautifulSoup

# ========== CONFIGURATION ==========
BASE_URL = "https://nowplayer.now.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Keywords to identify sports live events (case-insensitive)
SPORTS_KEYWORDS = [
    "premier league", "la liga", "serie a", "bundesliga", "ligue 1",
    "champions league", "europa league", "fa cup", "carabao cup",
    "wta", "atp", "tennis", "football", "soccer", "live", "vs", " v ", " - "
]

# Only channels whose name starts with "now Sports" (case-insensitive)
CHANNEL_NAME_FILTER = "now Sports"

# Vietnam timezone (UTC+7)
VIETNAM_TZ = pytz.timezone("Asia/Ho_Chi_Minh")
# ===================================

# ---------- Helper Functions ----------
def fetch_channels() -> Dict[str, str]:
    """
    Fetch channel list from NowTV and return mapping {channelNo: channelName}.
    Only includes channels matching CHANNEL_NAME_FILTER.
    """
    print("📡 Fetching channel list (English mode)...")
    url = f"{BASE_URL}/channels"
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en,zh;q=0.9"}

    # Request English language version
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
            # Filter: keep only channels starting with "now Sports"
            if name.lower().startswith(CHANNEL_NAME_FILTER.lower()):
                channel_map[ch_no] = name

    print(f"✅ Found {len(channel_map)} 'now Sports' channels.")
    return channel_map


def fetch_7day_epg(channel_numbers: List[str]) -> Dict[int, List[List[Dict]]]:
    """
    Fetch 7-day EPG data for given channel numbers using the internal API.
    Returns dict: day (1..7) -> list of channel arrays (each array corresponds to a channel)
    """
    print("📡 Fetching 7-day EPG data...")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/plain, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": f"{BASE_URL}/tvguide",
        "X-Requested-With": "XMLHttpRequest",
    }
    # English language for EPG titles
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


def extract_league_matchup(title: str) -> (str, str):
    """
    Parse English title into League and Matchup.
    Common patterns:
      "Premier League: Arsenal vs Liverpool"
      "WTA Tour 2026 - Open Capfinances Rouen Metropole SF"
      "Champions League Live: Real Madrid v Barcelona"
    """
    # Remove trailing "LIVE" or "直播" indicators for cleaner parsing
    clean_title = re.sub(r"\s*[-–:]?\s*(LIVE|直播)\s*$", "", title, flags=re.IGNORECASE).strip()

    # Try to split by colon, dash, or " - "
    pattern_split = re.compile(r"\s*[:：\-–]\s*")
    parts = pattern_split.split(clean_title, maxsplit=1)

    if len(parts) == 2:
        league_candidate = parts[0].strip()
        matchup_candidate = parts[1].strip()
        # If league part looks reasonable (contains known league keywords or is short)
        if any(kw in league_candidate.lower() for kw in ["league", "cup", "tour", "open", "wta", "atp", "series"]):
            return league_candidate, matchup_candidate
        else:
            # Fallback: first part might be sport name, second is matchup
            return "Sports", clean_title
    else:
        # No split: return whole as matchup, league unknown
        return "Unknown League", clean_title


def parse_sports_programs(epg_data: Dict[int, List[List[Dict]]],
                          channel_numbers: List[str],
                          channel_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """
    Parse raw EPG data, filter sports events, and extract league/matchup.
    Returns list of JSON-ready events.
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

                # Check if it's a sports event using keywords
                title_lower = title.lower()
                if not any(kw in title_lower for kw in SPORTS_KEYWORDS):
                    continue

                # Strong indicator of a match: contains "vs" or " v "
                if " vs " not in title_lower and " v " not in title_lower:
                    # Still allow tennis/WTA/ATP without explicit vs
                    if not any(kw in title_lower for kw in ["wta", "atp", "tennis", "open"]):
                        continue

                # Timestamp conversion to Vietnam time
                start_ts = epg_item.get("start", 0) / 1000
                end_ts = epg_item.get("end", 0) / 1000
                dt_start = datetime.fromtimestamp(start_ts, tz=VIETNAM_TZ)
                dt_end = datetime.fromtimestamp(end_ts, tz=VIETNAM_TZ)

                # Extract League and Matchup
                league, matchup = extract_league_matchup(title)

                # Build event record
                events.append({
                    "Date": dt_start.strftime("%Y-%m-%d"),
                    "Time": dt_start.strftime("%H:%M"),
                    "League": league,
                    "Matchup": matchup,
                    "Services": [ch_name],
                    # Optional metadata (can be removed before final output)
                    "_start_iso": dt_start.isoformat(),
                    "_end_iso": dt_end.isoformat(),
                    "_raw_title": title,
                    "_channel_no": ch_no
                })
    return events


def deduplicate_events(events: List[Dict]) -> List[Dict]:
    """
    Merge events that are identical but air on multiple channels.
    """
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
    print("🚀 Now TV Sports Schedule Extractor (English - Vietnam Time)")
    # 1. Get channels (filtered to "now Sports")
    channel_map = fetch_channels()
    if not channel_map:
        print("❌ No 'now Sports' channels found.")
        sys.exit(1)

    channel_numbers = list(channel_map.keys())

    # 2. Fetch EPG
    epg_data = fetch_7day_epg(channel_numbers)

    # 3. Parse sports programs
    print("🔍 Parsing sports programs...")
    events = parse_sports_programs(epg_data, channel_numbers, channel_map)

    # 4. Deduplicate (same match on multiple channels)
    events = deduplicate_events(events)
    print(f"🎯 Found {len(events)} unique sports events.")

    # 5. Sort by date/time
    events.sort(key=lambda x: (x["Date"], x["Time"]))

    # 6. Prepare clean output (only required fields)
    output_events = []
    for ev in events:
        output_events.append({
            "Date": ev["Date"],
            "Time": ev["Time"],
            "League": ev["League"],
            "Matchup": ev["Matchup"],
            "Services": ev["Services"]
        })

    # 7. Write to file
    output_file = "nowtv_sports_schedule_en.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_events, f, ensure_ascii=False, indent=2)
    print(f"💾 Schedule saved to {output_file}")

    # Print sample to console
    print("\n📋 Sample output (first 5 events):")
    for ev in output_events[:5]:
        print(f"{ev['Date']} {ev['Time']} | {ev['League']} - {ev['Matchup']} | {', '.join(ev['Services'])}")


if __name__ == "__main__":
    asyncio.run(main())
