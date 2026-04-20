#!/usr/bin/env python3
"""
Now TV Sports Live Schedule Extractor (English - Vietnam Time)
Fetches EPG from Now TV, filters only "now Sports" channels,
extracts football/tennis live events, merges pre-match shows, outputs JSON.
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

CHANNEL_NAME_FILTER = "now Sports"
VIETNAM_TZ = pytz.timezone("Asia/Ho_Chi_Minh")

ALLOWED_FOOTBALL_LEAGUES: Set[str] = {
    "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "UEFA Euro", "FA Cup", "League Cup", "FIFA World Cup", "International Friendly"
}

TENNIS_KEYWORDS: Set[str] = {
    "atp", "wta", "atp tour", "wta tour", "atp world tour",
    "grand slam", "australian open", "roland garros", "french open",
    "wimbledon", "us open", "nitto atp finals",
    "atp masters", "atp 1000", "atp 500", "atp 250",
    "wta 1000", "wta 500", "wta 250",
    "davis cup", "billie jean king cup", "laver cup"
}
# ===================================

def fetch_channels() -> Dict[str, str]:
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
            resp = requests.get(f"{BASE_URL}/tvguide/epglist", headers=headers, cookies=cookies, params=params, timeout=10)
            resp.raise_for_status()
            epg_data[day] = resp.json()
            print(f"  Day {day}: OK")
        except Exception as e:
            print(f"  Day {day}: Failed - {e}")
            epg_data[day] = []
    return epg_data

def clean_brackets(text: str) -> str:
    return re.sub(r"\[.*?\]", "", text).strip()

def is_live(title: str) -> bool:
    return bool(re.search(r"\[Live\]", title, re.IGNORECASE))

def is_football_league_allowed(text: str) -> bool:
    text_lower = text.lower()
    return any(allowed.lower() in text_lower for allowed in ALLOWED_FOOTBALL_LEAGUES)

def is_tennis_event(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in TENNIS_KEYWORDS)

def extract_league_matchup(raw_title: str) -> Tuple[str, str]:
    cleaned = clean_brackets(raw_title)
    cleaned = re.sub(r"\s*Live\s*$", "", cleaned, flags=re.IGNORECASE).strip()

    # Tennis pattern: "WTA 26 Porsche Tennis Grand Prix Final"
    tennis_pattern = re.compile(r"^(ATP|WTA)\s+\d{1,4}\b", re.IGNORECASE)
    tennis_match = tennis_pattern.search(cleaned)
    if tennis_match:
        league_part = tennis_match.group(0)
        matchup_part = cleaned[tennis_match.end():].strip()
        return league_part, matchup_part if matchup_part else cleaned

    # General split by colon or dash
    parts = re.split(r"\s*[:：\-–]\s*", cleaned, maxsplit=1)
    if len(parts) == 2:
        league = re.sub(r"\s*Live\b", "", parts[0], flags=re.IGNORECASE).strip()
        matchup = re.sub(r"\s*Live\b", "", parts[1], flags=re.IGNORECASE).strip()
        return league, matchup
    else:
        return "", cleaned

def parse_sports_programs(epg_data, channel_numbers, channel_map):
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
                if not title or not is_live(title):
                    continue
                if not (is_football_league_allowed(title) or is_tennis_event(title)):
                    continue

                # Premier League: must contain " vs " or " v "
                if "premier league" in title.lower():
                    if not re.search(r"\s+vs\s+|\s+v\s+", title, re.IGNORECASE):
                        continue

                league, matchup = extract_league_matchup(title)
                if not league and is_tennis_event(title):
                    first_word = title.split()[0]
                    if first_word.upper() in ("ATP", "WTA"):
                        league = first_word.upper()
                        matchup = title[len(first_word):].strip()
                    else:
                        league = "Tennis"
                        matchup = title
                if not league:
                    league = "Sports"
                if not matchup:
                    matchup = title

                start_ts = epg_item.get("start", 0) / 1000
                dt_start = datetime.fromtimestamp(start_ts, tz=VIETNAM_TZ)
                events.append({
                    "Date": dt_start.strftime("%Y-%m-%d"),
                    "Time": dt_start.strftime("%H:%M"),
                    "League": league,
                    "Matchup": matchup,
                    "Services": [ch_name],
                })
    return events

def normalize_matchup(matchup: str) -> str:
    """Lowercase and remove punctuation/spaces for comparison."""
    norm = matchup.lower()
    norm = re.sub(r'[^\w\s]', '', norm)  # remove punctuation
    norm = re.sub(r'\s+', ' ', norm).strip()
    return norm

def deduplicate_events(events: List[Dict]) -> List[Dict]:
    """
    Merge events that are the same match but with different start times
    (pre-match shows). Keep the latest time if within 30 minutes.
    """
    # Group by date and normalized matchup
    groups = {}
    for ev in events:
        date = ev["Date"]
        matchup_norm = normalize_matchup(ev["Matchup"])
        key = (date, matchup_norm)
        if key not in groups:
            groups[key] = []
        groups[key].append(ev)

    merged = []
    for (date, norm_matchup), ev_list in groups.items():
        if len(ev_list) == 1:
            merged.append(ev_list[0])
            continue

        # Sort by time ascending
        ev_list.sort(key=lambda x: x["Time"])

        # Cluster by time difference <= 30 minutes
        clusters = []
        current_cluster = [ev_list[0]]
        for i in range(1, len(ev_list)):
            prev_time = datetime.strptime(current_cluster[-1]["Time"], "%H:%M")
            curr_time = datetime.strptime(ev_list[i]["Time"], "%H:%M")
            diff = (curr_time - prev_time).total_seconds() / 60
            if diff <= 30:
                current_cluster.append(ev_list[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [ev_list[i]]
        clusters.append(current_cluster)

        # For each cluster, keep the latest time and merge services
        for cluster in clusters:
            latest_ev = max(cluster, key=lambda x: x["Time"])
            all_services = set()
            for ev in cluster:
                all_services.update(ev["Services"])
            merged_ev = latest_ev.copy()
            merged_ev["Services"] = sorted(list(all_services))
            merged.append(merged_ev)

    return merged

async def main():
    print("🚀 Now TV Sports Live Schedule Extractor (Merging pre-match shows)")
    channel_map = fetch_channels()
    if not channel_map:
        print("❌ No 'now Sports' channels found.")
        sys.exit(1)
    channel_numbers = list(channel_map.keys())
    epg_data = fetch_7day_epg(channel_numbers)
    print("🔍 Parsing and filtering live sports events...")
    events = parse_sports_programs(epg_data, channel_numbers, channel_map)
    print(f"📊 Raw events before dedup: {len(events)}")
    events = deduplicate_events(events)
    print(f"🎯 Unique events after merging pre-match: {len(events)}")
    events.sort(key=lambda x: (x["Date"], x["Time"]))
    output_events = [{k: v for k, v in ev.items() if k != "_raw"} for ev in events]
    with open("nowtv_sports_schedule_en.json", "w", encoding="utf-8") as f:
        json.dump(output_events, f, ensure_ascii=False, indent=2)
    print("💾 Schedule saved to nowtv_sports_schedule_en.json")
    print("\n📋 Sample (first 5):")
    for ev in output_events[:5]:
        print(f"{ev['Date']} {ev['Time']} | {ev['League']} | {ev['Matchup']} | {', '.join(ev['Services'])}")

if __name__ == "__main__":
    asyncio.run(main())
