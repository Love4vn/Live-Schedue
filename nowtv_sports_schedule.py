#!/usr/bin/env python3
"""
Combined Now TV & Ziggo Sport Live Sports Schedule Extractor
Output: nowtv_sports_schedule_en.json (events from both sources)
"""

import asyncio
import json
import re
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Set

import pytz
import requests
from bs4 import BeautifulSoup

# ========== CONFIG ==========
VIETNAM_TZ = pytz.timezone("Asia/Ho_Chi_Minh")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

ALLOWED_FOOTBALL_LEAGUES = {
    "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "UEFA Euro", "FA Cup", "League Cup", "FIFA World Cup", "International Friendly"
}

TENNIS_KEYWORDS = {
    "atp", "wta", "atp tour", "wta tour", "atp world tour",
    "grand slam", "australian open", "roland garros", "french open",
    "wimbledon", "us open", "nitto atp finals",
    "atp masters", "atp 1000", "atp 500", "atp 250",
    "wta 1000", "wta 500", "wta 250",
    "davis cup", "billie jean king cup", "laver cup"
}
# ===============================

# ---------- Helper Functions ----------
def normalize_matchup(matchup: str) -> str:
    text = matchup.lower()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def clean_brackets(text: str) -> str:
    return re.sub(r"\[.*?\]", "", text).strip()

def is_live(title: str) -> bool:
    return bool(re.search(r"\[Live\]", title, re.IGNORECASE))

def extract_league_matchup(title: str) -> Tuple[str, str]:
    cleaned = clean_brackets(title)
    cleaned = re.sub(r"\s*Live\s*$", "", cleaned, flags=re.IGNORECASE).strip()

    tennis_pattern = re.compile(r"^(ATP|WTA)\s+\d{1,4}\b", re.IGNORECASE)
    tennis_match = tennis_pattern.search(cleaned)
    if tennis_match:
        league_part = tennis_match.group(0)
        matchup_part = cleaned[tennis_match.end():].strip()
        return league_part, matchup_part if matchup_part else cleaned

    parts = re.split(r"\s*[:：\-–]\s*", cleaned, maxsplit=1)
    if len(parts) == 2:
        league = re.sub(r"\s*Live\b", "", parts[0], flags=re.IGNORECASE).strip()
        matchup = re.sub(r"\s*Live\b", "", parts[1], flags=re.IGNORECASE).strip()
        matchup = re.sub(r"\s+-\s+", " vs ", matchup)
        return league, matchup
    else:
        return "", cleaned

def is_football_league_allowed(text: str) -> bool:
    text_lower = text.lower()
    return any(allowed.lower() in text_lower for allowed in ALLOWED_FOOTBALL_LEAGUES)

def is_tennis_event(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in TENNIS_KEYWORDS)

# ---------- Now TV Fetcher ----------
class NowTVFetcher:
    def __init__(self):
        self.base_url = "https://nowplayer.now.com"
        self.channel_filter = "now Sports"

    def fetch_channels(self) -> Dict[str, str]:
        print("📡 [NowTV] Fetching channels...")
        url = f"{self.base_url}/channels"
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "en,zh;q=0.9"}
        resp = requests.get(url, headers=headers, cookies={"LANG": "en"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        channel_map = {}
        for item in soup.find_all("div", class_="product-item"):
            name_tag = item.find("p", class_="img-name")
            ch_tag = item.find("p", class_="channel")
            if name_tag and ch_tag:
                name = name_tag.text.strip()
                ch_no = ch_tag.text.replace("CH", "").strip()
                if name.lower().startswith(self.channel_filter.lower()):
                    channel_map[ch_no] = name
        print(f"✅ [NowTV] {len(channel_map)} 'now Sports' channels found.")
        return channel_map

    def fetch_7day_epg(self, channel_numbers: List[str]) -> Dict[int, List[List[Dict]]]:
        print("📡 [NowTV] Fetching 7-day EPG...")
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/plain, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": f"{self.base_url}/tvguide",
            "X-Requested-With": "XMLHttpRequest",
        }
        cookies = {"LANG": "en"}
        epg_data = {}
        for day in range(1, 8):
            params = [("channelIdList[]", ch) for ch in channel_numbers] + [("day", str(day))]
            try:
                resp = requests.get(f"{self.base_url}/tvguide/epglist", headers=headers,
                                    cookies=cookies, params=params, timeout=10)
                resp.raise_for_status()
                epg_data[day] = resp.json()
                print(f"  Day {day}: OK")
            except Exception as e:
                print(f"  Day {day}: Failed - {e}")
                epg_data[day] = []
        return epg_data

    def parse_events(self, epg_data, channel_numbers, channel_map) -> List[Dict]:
        events = []
        for day in range(1, 8):
            day_progs = epg_data.get(day, [])
            for idx, channel_progs in enumerate(day_progs):
                if idx >= len(channel_numbers):
                    continue
                ch_no = channel_numbers[idx]
                ch_name = channel_map.get(ch_no, f"Channel {ch_no}")
                for epg_item in channel_progs:
                    title = (epg_item.get("name") or "").strip()
                    if not title or not is_live(title):
                        continue
                    if not (is_football_league_allowed(title) or is_tennis_event(title)):
                        continue
                    if "premier league" in title.lower():
                        if not re.search(r"\s+vs\s+|\s+v\s+", title, re.IGNORECASE):
                            continue

                    league, matchup = extract_league_matchup(title)
                    if not league and is_tennis_event(title):
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

# ---------- Ziggo Sport Fetcher ----------
class ZiggoFetcher:
    def __init__(self):
        self.base_url = "https://www.ziggosport.nl"

    def get_available_dates(self) -> List[str]:
        index_url = f"{self.base_url}/cache/site/ZiggosportNL/json/epg/index.json"
        try:
            resp = requests.get(index_url)
            resp.raise_for_status()
            files = resp.json()
            dates = [f.split("-", 1)[1].split(".")[0] for f in files]
            return sorted(dates)
        except Exception as e:
            print(f"❌ [Ziggo] Failed to load index: {e}")
            return []

    def fetch_epg_for_date(self, date_str: str) -> List[Dict]:
        url = f"{self.base_url}/cache/site/ZiggosportNL/json/epg/epg-{date_str}.json"
        try:
            resp = requests.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"❌ [Ziggo] Failed to fetch {date_str}: {e}")
            return []

    def parse_events(self, days: int = 7) -> List[Dict]:
        all_dates = self.get_available_dates()
        today = datetime.now().strftime("%Y-%m-%d")
        future_dates = sorted([d for d in all_dates if d >= today])[:days]
        events = []
        for date_str in future_dates:
            data = self.fetch_epg_for_date(date_str)
            if not data:
                continue
            for channel_data in data:
                channel_name = channel_data.get("channel", "Unknown Channel")
                for prog in channel_data.get("programming", []):
                    if not prog.get("live"):
                        continue
                    # sportName could be null -> use empty string instead of None
                    sport_name = (prog.get("sportName") or "").lower()
                    if sport_name not in ("voetbal", "tennis"):
                        continue
                    title = (prog.get("title") or "").strip()
                    if not title:
                        continue
                    league, matchup = extract_league_matchup(title)
                    if not league:
                        if sport_name == "tennis":
                            league = "Tennis"
                        elif sport_name == "voetbal":
                            league = "Football"
                        else:
                            league = "Sports"
                    if not matchup:
                        matchup = title

                    start_ts = prog.get("timeStart")
                    if start_ts:
                        dt_start = datetime.fromtimestamp(start_ts, tz=VIETNAM_TZ)
                        date_formatted = dt_start.strftime("%Y-%m-%d")
                        time_formatted = dt_start.strftime("%H:%M")
                    else:
                        date_formatted = date_str
                        time_formatted = "00:00"

                    events.append({
                        "Date": date_formatted,
                        "Time": time_formatted,
                        "League": league,
                        "Matchup": matchup,
                        "Services": [channel_name],
                    })
        return events

# ---------- Deduplication ----------
def deduplicate_events(events: List[Dict]) -> List[Dict]:
    groups = {}
    for ev in events:
        date = ev["Date"]
        norm = normalize_matchup(ev["Matchup"])
        key = (date, norm)
        groups.setdefault(key, []).append(ev)

    merged = []
    for (date, norm_matchup), ev_list in groups.items():
        if len(ev_list) == 1:
            merged.append(ev_list[0])
            continue
        ev_list.sort(key=lambda x: x["Time"])
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

        for cluster in clusters:
            latest_ev = max(cluster, key=lambda x: x["Time"])
            all_services = set()
            for ev in cluster:
                all_services.update(ev["Services"])
            merged_ev = latest_ev.copy()
            merged_ev["Services"] = sorted(list(all_services))
            merged.append(merged_ev)
    return merged

# ---------- Main ----------
async def main():
    print("🚀 Combined Now TV & Ziggo Sport Live Schedule Extractor")

    nowtv = NowTVFetcher()
    nowtv_channels = nowtv.fetch_channels()
    nowtv_events = []
    if nowtv_channels:
        ch_numbers = list(nowtv_channels.keys())
        epg = nowtv.fetch_7day_epg(ch_numbers)
        nowtv_events = nowtv.parse_events(epg, ch_numbers, nowtv_channels)
        print(f"🎯 [NowTV] {len(nowtv_events)} raw events")
    else:
        print("⚠️ [NowTV] No channels, skipping.")

    ziggo = ZiggoFetcher()
    ziggo_events = ziggo.parse_events(days=7)
    print(f"🎯 [Ziggo] {len(ziggo_events)} raw events")

    all_events = nowtv_events + ziggo_events
    print(f"📊 Combined raw events: {len(all_events)}")

    all_events = deduplicate_events(all_events)
    print(f"✅ After dedup: {len(all_events)} events")

    all_events.sort(key=lambda x: (x["Date"], x["Time"]))

    output = []
    for ev in all_events:
        output.append({
            "Date": ev["Date"],
            "Time": ev["Time"],
            "League": ev["League"],
            "Matchup": ev["Matchup"],
            "Services": ev["Services"]
        })

    with open("nowtv_sports_schedule_en.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"💾 File saved: nowtv_sports_schedule_en.json")

    print("\n📋 Sample (first 5):")
    for ev in output[:5]:
        print(f"{ev['Date']} {ev['Time']} | {ev['League']} | {ev['Matchup']} | {', '.join(ev['Services'])}")

if __name__ == "__main__":
    asyncio.run(main())
