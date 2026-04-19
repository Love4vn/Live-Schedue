#!/usr/bin/env python3
"""
Now TV Sports Live Schedule Extractor
Extracts football and tennis live events from Now TV EPG and outputs JSON.
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
SPORTS_KEYWORDS = [
    "英超", "西甲", "意甲", "德甲", "法甲", "歐聯", "歐霸", "世界盃", "歐洲國家盃",
    "Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1",
    "Champions League", "Europa League", "FA Cup", "Carabao Cup",
    "WTA", "ATP", "Tennis", "網球", "足球", "LIVE", "直播"
]
# Channels likely to show sports (optional filtering)
SPORTS_CHANNEL_PREFIXES = ("now Sports", "Hub Sports", "Premier", "beIN", "Sports")
# ===================================

TZ_SHANGHAI = pytz.timezone("Asia/Shanghai")

# ---------- Helper Functions ----------
def fetch_channels() -> Dict[str, str]:
    """Fetch channel list from NowTV and return mapping {channelNo: channelName}."""
    print("📡 Fetching channel list...")
    url = f"{BASE_URL}/channels"
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "zh,en;q=0.9"}
    resp = requests.get(url, headers=headers, cookies={"LANG": "zh"})
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    channel_map = {}

    for item in soup.find_all("div", class_="product-item"):
        name_tag = item.find("p", class_="img-name")
        channel_tag = item.find("p", class_="channel")
        if name_tag and channel_tag:
            name = name_tag.text.strip()
            ch_no = channel_tag.text.replace("CH", "").strip()
            channel_map[ch_no] = name

    print(f"✅ Found {len(channel_map)} channels.")
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
    cookies = {"LANG": "zh"}

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


def parse_sports_programs(epg_data: Dict[int, List[List[Dict]]],
                          channel_numbers: List[str],
                          channel_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """
    Parse raw EPG data, filter sports events, and extract league/matchup.
    Returns list of JSON-ready events.
    """
    events = []
    # Regex to split title into League and Matchup
    # Common patterns: "League: Team A vs Team B", "League - Team A vs Team B"
    pattern_split = re.compile(r"[:：\-–]\s*")
    # Also try to identify league keywords
    league_keywords = [
        "Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1",
        "Champions League", "Europa League", "FA Cup", "Carabao Cup",
        "WTA", "ATP", "英超", "西甲", "意甲", "德甲", "法甲", "歐聯", "歐霸"
    ]

    for day in range(1, 8):
        day_progs = epg_data.get(day, [])
        for idx, channel_progs in enumerate(day_progs):
            if idx >= len(channel_numbers):
                continue
            ch_no = channel_numbers[idx]
            ch_name = channel_map.get(ch_no, f"Channel {ch_no}")

            # Optional: skip non-sports channels for performance
            # if not any(ch_name.startswith(p) for p in SPORTS_CHANNEL_PREFIXES):
            #     continue

            for epg_item in channel_progs:
                title = epg_item.get("name", "").strip()
                if not title:
                    continue

                # Filter sports content
                if not any(kw.lower() in title.lower() for kw in SPORTS_KEYWORDS):
                    continue

                # Prefer live events (optional, but helps)
                if "直播" not in title and "LIVE" not in title.upper():
                    # Still keep it if it's clearly a sports match
                    if not any(kw in title for kw in ["vs", "對", "VS"]):
                        continue

                # Timestamp conversion
                start_ts = epg_item.get("start", 0) / 1000
                end_ts = epg_item.get("end", 0) / 1000
                dt_start = datetime.fromtimestamp(start_ts, tz=TZ_SHANGHAI)
                dt_end = datetime.fromtimestamp(end_ts, tz=TZ_SHANGHAI)

                # Extract League and Matchup
                league, matchup = extract_league_matchup(title, pattern_split, league_keywords)

                # Build event record
                events.append({
                    "Date": dt_start.strftime("%Y-%m-%d"),
                    "Time": dt_start.strftime("%H:%M"),
                    "League": league,
                    "Matchup": matchup,
                    "Services": [ch_name],
                    # Additional fields (optional)
                    "StartTimestamp": dt_start.isoformat(),
                    "EndTimestamp": dt_end.isoformat(),
                    "RawTitle": title,
                    "ChannelNumber": ch_no
                })
    return events


def extract_league_matchup(title: str, pattern_split, league_keywords) -> (str, str):
    """
    Parse title into League and Matchup.
    """
    # Try to split by colon/dash
    parts = pattern_split.split(title, maxsplit=1)
    if len(parts) == 2:
        league_candidate = parts[0].strip()
        matchup_candidate = parts[1].strip()
        # If first part looks like a league keyword, use it
        if any(lk.lower() in league_candidate.lower() for lk in league_keywords):
            return league_candidate, matchup_candidate
        else:
            # Maybe the first part is sport type, second is matchup
            return "Sports", title
    else:
        # No split found: use whole title as matchup, league unknown
        return "Unknown League", title


def deduplicate_events(events: List[Dict]) -> List[Dict]:
    """
    Merge events that are identical but on different channels (multi-channel broadcast).
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
    print("🚀 Now TV Sports Schedule Extractor")
    # 1. Get channels
    channel_map = fetch_channels()
    if not channel_map:
        print("❌ No channels found.")
        sys.exit(1)

    # Use all channel numbers (or optionally filter sports channels)
    channel_numbers = list(channel_map.keys())
    # Optionally filter to likely sports channels to reduce API load
    # sports_channel_numbers = [no for no, name in channel_map.items()
    #                          if any(name.startswith(p) for p in SPORTS_CHANNEL_PREFIXES)]
    # if sports_channel_numbers:
    #     channel_numbers = sports_channel_numbers
    #     print(f"⚽ Filtered to {len(channel_numbers)} sports-related channels.")

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

    # 6. Output JSON
    # Remove extra fields to match exact required format
    output_events = []
    for ev in events:
        output_events.append({
            "Date": ev["Date"],
            "Time": ev["Time"],
            "League": ev["League"],
            "Matchup": ev["Matchup"],
            "Services": ev["Services"]
        })

    # Write to file or stdout
    output_file = "nowtv_sports_schedule.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_events, f, ensure_ascii=False, indent=2)
    print(f"💾 Schedule saved to {output_file}")

    # Also print to stdout for GitHub Actions logging
    print(json.dumps(output_events, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
