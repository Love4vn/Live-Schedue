#!/usr/bin/env python3
"""
football_tv_scraper.py
================================
Scraper tổng hợp lịch bóng đá và tennis từ các nguồn:
- SofaScore (global)
- LiveSportsOnTV (UK)
- WorldSoccerTalk (US)
- Matchs.tv (FR)
- LiveSoccerTV (UK top matches)

Xuất file schedule_merged.json và các file riêng.
"""

import asyncio
import json
import re
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Any
from difflib import SequenceMatcher

import pycountry
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ================== CẤU HÌNH ==================
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
UK_TIMEZONE = ZoneInfo("Europe/London")
US_TIMEZONE = ZoneInfo("America/New_York")
FR_TIMEZONE = ZoneInfo("Europe/Paris")

OUTPUT_DIR = "."  # current directory

# Các giải và đội được phép (giống như yêu cầu trước)
ALLOWED_TEAMS_PER_LEAGUE = {
    "Premier League": {"arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
                       "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
                       "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
                       "west ham united", "wolverhampton"},
    "Serie A": {"inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"},
    "La Liga": {"barcelona", "real madrid", "atlético"},
    "Bundesliga": {"bayern", "borussia dortmund", "bayer leverkusen"},
    "Ligue 1": {"psg", "olympique marseille"},
    "UEFA Champions League": None,
    "UEFA Europa League": None,
    "UEFA Europa Conference League": None,
}

ALLOWED_TENNIS_TOURNAMENTS = {
    "atp", "wta", "grand slam", "australian open", "french open", "roland garros",
    "wimbledon", "us open", "us open tennis", "the championships"
}

# ================== HELPER ==================
def normalize(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.split())

def vn_time(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC")).astimezone(TIMEZONE)
    return dt.strftime("%d/%m %I:%M %p")

def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def save_games(filename: str, games: List[Dict]):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(games, f, indent=2, ensure_ascii=False)
    print(f"   ✅ Đã lưu {len(games)} trận vào {filename}")

# ================== SOFASCORE ==================
async def get_channel_name(session, channel_id):
    url = f"https://api.sofascore.com/api/v1/tv/channel/{channel_id}/schedule"
    try:
        res = await session.get(url, impersonate="chrome120", timeout=5)
        if res.status_code == 200:
            return res.json().get('channel', {}).get('name', 'Unknown')
    except:
        pass
    return "Unknown"

async def get_tv_data(session, event_id):
    url = f"https://api.sofascore.com/api/v1/tv/event/{event_id}/country-channels"
    try:
        res = await session.get(url, impersonate="chrome120", timeout=10)
        if res.status_code != 200: return []
        data = res.json().get('countryChannels', {})
        broadcasters = []
        for code, cids in data.items():
            country = pycountry.countries.get(alpha_2=code).name if pycountry.countries.get(alpha_2=code) else code
            names = await asyncio.gather(*[get_channel_name(session, cid) for cid in cids])
            clean = list(set([n for n in names if n != "Unknown"]))
            if clean:
                broadcasters.append({"country": country, "channels": clean})
        return broadcasters
    except:
        return []

async def fetch_sofascore_event(session, event_id, sport, now_ts, max_ts):
    url = f"https://api.sofascore.com/api/v1/event/{event_id}"
    try:
        res = await session.get(url, impersonate="chrome120", timeout=10)
        if res.status_code != 200: return None
        ev = res.json().get('event', {})
        start_ts = ev.get('startTimestamp')
        if not start_ts or not (now_ts <= start_ts <= max_ts):
            return None

        tv = await get_tv_data(session, event_id)

        if sport == "tennis":
            tournament = ev.get('tournament', {}).get('name', '').lower()
            if not any(kw in tournament for kw in ALLOWED_TENNIS_TOURNAMENTS):
                return None
            return {
                "source": "sofascore",
                "league": "Tennis",
                "time": vn_time(start_ts),
                "match": f"{ev.get('homeTeam', {}).get('name', '')} vs {ev.get('awayTeam', {}).get('name', '')}",
                "kick_utc": start_ts,
                "tv_channels": tv,
                "tournament": ev.get('tournament', {}).get('name')
            }
        else:
            league_raw = ev.get('tournament', {}).get('name', 'Unknown')
            league_lower = league_raw.lower()
            if not any(kw in league_lower for kw in ["premier league", "serie a", "bundesliga", "la liga", "laliga", "ligue 1", "uefa champions", "uefa europa league", "conference league"]):
                return None

            if "la liga" in league_lower or "laliga" in league_lower:
                league = "La Liga"
            elif "premier" in league_lower:
                league = "Premier League"
            elif "serie" in league_lower:
                league = "Serie A"
            elif "bundes" in league_lower:
                league = "Bundesliga"
            elif "ligue" in league_lower:
                league = "Ligue 1"
            elif "champions" in league_lower:
                league = "UEFA Champions League"
            elif "europa league" in league_lower:
                league = "UEFA Europa League"
            elif "conference" in league_lower:
                league = "UEFA Europa Conference League"
            else:
                league = league_raw

            allowed_teams = ALLOWED_TEAMS_PER_LEAGUE.get(league)
            if allowed_teams is not None:
                home = ev.get('homeTeam', {}).get('name', '').lower()
                away = ev.get('awayTeam', {}).get('name', '').lower()
                if not (any(t in home for t in allowed_teams) or any(t in away for t in allowed_teams)):
                    return None

            return {
                "source": "sofascore",
                "league": league,
                "time": vn_time(start_ts),
                "match": f"{ev.get('homeTeam', {}).get('name', '')} vs {ev.get('awayTeam', {}).get('name', '')}",
                "kick_utc": start_ts,
                "tv_channels": tv,
                "tournament": league_raw
            }
    except:
        return None

async def scrape_sofascore() -> List[Dict]:
    all_games = []
    async with AsyncSession() as session:
        for sport in ["football", "tennis"]:
            now = datetime.now()
            dates = [now.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")]
            now_ts = int(datetime.now(TIMEZONE).timestamp())
            max_ts = now_ts + 86400

            for date_str in dates:
                url = f"https://www.sofascore.com/api/v1/sport/{sport}/scheduled-events/{date_str}"
                try:
                    res = await session.get(url, impersonate="chrome120", timeout=30)
                    if res.status_code != 200: continue
                    events = res.json().get('events', [])
                    tasks = [fetch_sofascore_event(session, e['id'], sport, now_ts, max_ts) for e in events]
                    results = await asyncio.gather(*tasks)
                    all_games.extend([r for r in results if r])
                except:
                    continue
            await asyncio.sleep(1)
    return all_games

# ================== LIVESPORTSONTV (UK) ==================
LIVESPORTS_CONFIG = {
    "Premier League": {"url": "https://www.livesportsontv.com/league/premier-league", "teams": ALLOWED_TEAMS_PER_LEAGUE["Premier League"]},
    "Serie A": {"url": "https://www.livesportsontv.com/league/serie-a", "teams": ALLOWED_TEAMS_PER_LEAGUE["Serie A"]},
    "La Liga": {"url": "https://www.livesportsontv.com/league/la-liga", "teams": ALLOWED_TEAMS_PER_LEAGUE["La Liga"]},
    "Bundesliga": {"url": "https://www.livesportsontv.com/league/bundesliga-5", "teams": ALLOWED_TEAMS_PER_LEAGUE["Bundesliga"]},
    "Ligue 1": {"url": "https://www.livesportsontv.com/league/ligue-1-3", "teams": ALLOWED_TEAMS_PER_LEAGUE["Ligue 1"]},
    "UEFA Champions League": {"url": "https://www.livesportsontv.com/league/uefa-champions-league", "teams": None},
    "UEFA Europa League": {"url": "https://www.livesportsontv.com/league/uefa-europa-league", "teams": None},
    "UEFA Europa Conference League": {"url": "https://www.livesportsontv.com/league/uefa-conference-league", "teams": None},
    "Tennis (ATP)": {"url": "https://www.livesportsontv.com/league/atp", "teams": None},
    "Tennis (WTA)": {"url": "https://www.livesportsontv.com/league/wta", "teams": None},
}

async def scrape_livesportsontv() -> List[Dict]:
    all_games = []
    now_ts = int(datetime.now(TIMEZONE).timestamp())
    max_ts = now_ts + 86400

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        page = await browser.new_page()
        page.set_default_navigation_timeout(120000)
        page.set_default_timeout(60000)

        for league_name, config in LIVESPORTS_CONFIG.items():
            print(f"   [LiveSports] Đang xử lý {league_name}...")
            url = config["url"]
            team_filter = config["teams"]

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=120000)
                for _ in range(4):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(1500)

                html = await page.content()
                soup = BeautifulSoup(html, 'html.parser')
                game_rows = soup.find_all('div', class_='event--wrapp')

                for row in game_rows:
                    try:
                        time_tag = row.find('time')
                        if not time_tag:
                            continue
                        dt_attr = time_tag.get('datetime')
                        if dt_attr:
                            dt_obj = datetime.fromisoformat(dt_attr.replace('Z', '+00:00'))
                            if dt_obj.tzinfo is None:
                                dt_obj = dt_obj.replace(tzinfo=UK_TIMEZONE)
                            kick_utc = int(dt_obj.timestamp())
                        else:
                            date_div = row.find('div', class_='event__info--date')
                            if not date_div:
                                continue
                            day = date_div.find('b').get_text(strip=True)
                            month = date_div.find('span').get_text(strip=True)
                            time_str = time_tag.get_text(strip=True)
                            now_uk = datetime.now(UK_TIMEZONE)
                            year = now_uk.year
                            dt_obj = datetime.strptime(f"{day} {month} {year} {time_str}", "%d %b %Y %H:%M")
                            dt_obj = dt_obj.replace(tzinfo=UK_TIMEZONE)
                            if dt_obj < now_uk and (now_uk.month == 12 and dt_obj.month == 1):
                                dt_obj = dt_obj.replace(year=year+1)
                            kick_utc = int(dt_obj.timestamp())

                        if not (now_ts <= kick_utc <= max_ts):
                            continue

                        home_elem = row.find('div', class_=lambda c: c and 'event__participant--home' in c)
                        away_elem = row.find('div', class_=lambda c: c and 'event__participant--away' in c)
                        if not home_elem or not away_elem:
                            continue
                        home_team = home_elem.get_text(strip=True)
                        away_team = away_elem.get_text(strip=True)
                        match = f"{home_team} vs {away_team}"

                        if team_filter is not None:
                            if not any(t.lower() in home_team.lower() or t.lower() in away_team.lower() for t in team_filter):
                                continue

                        channels = []
                        channel_list = row.find('ul', class_='event__tags')
                        if channel_list:
                            for link in channel_list.find_all('a'):
                                if aria := link.get('aria-label'):
                                    channels.append(aria.strip())

                        all_games.append({
                            "source": "livesportsontv",
                            "league": "Tennis" if league_name.startswith("Tennis") else league_name,
                            "time": vn_time(kick_utc),
                            "match": match,
                            "kick_utc": kick_utc,
                            "tv_channels": [{"country": "United Kingdom", "channels": channels}] if channels else []
                        })
                    except Exception as e:
                        continue
            except Exception as e:
                print(f"   [LiveSports] Lỗi {league_name}: {e}")
                continue

        await browser.close()
    return all_games

# ================== WORLDSOCCERTALK (US) ==================
async def scrape_worldsoccertalk() -> List[Dict]:
    url = "https://worldsoccertalk.com/schedule/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    async with AsyncSession() as session:
        resp = await session.get(url, impersonate="chrome120", headers=headers, timeout=30)
        if resp.status_code != 200:
            print("[WorldSoccerTalk] Failed to fetch")
            return []
        html = resp.text

    soup = BeautifulSoup(html, 'lxml')
    games = []

    # Parse theo cấu trúc HTML của WorldSoccerTalk
    date_headers = soup.find_all('h3', class_='text-stvsDate')
    now_ts = int(datetime.now(TIMEZONE).timestamp())
    max_ts = now_ts + 86400

    for header in date_headers:
        date_text = header.get_text(strip=True)
        # Chuyển đổi date_text từ "Monday, March 17, 2026" thành datetime
        try:
            date_obj = datetime.strptime(date_text, "%A, %B %d, %Y")
        except:
            continue

        parent = header.find_parent()
        if not parent:
            continue
        match_rows = parent.find_all('li', class_='border-stvsMatchBorderColor')
        for row in match_rows:
            time_elem = row.find('div', class_='text-stvsMatchHour')
            if not time_elem:
                continue
            time_text = time_elem.get_text(strip=True)  # "7:30 PM ET"
            time_clean = time_text.replace(" ET", "").strip()
            try:
                dt_str = f"{date_text} {time_clean}"
                dt_et = datetime.strptime(dt_str, "%A, %B %d, %Y %I:%M %p")
                dt_et = dt_et.replace(tzinfo=US_TIMEZONE)
                kick_utc = int(dt_et.timestamp())
            except:
                continue

            if not (now_ts <= kick_utc <= max_ts):
                continue

            title_elem = row.find('div', class_='text-stvsMatchTitle')
            if not title_elem:
                continue
            title_text = title_elem.get_text(strip=True)
            # Tách đội và giải: "Team A vs Team B (Competition)"
            match_comp = title_text.split('(')
            if len(match_comp) >= 2:
                match = match_comp[0].strip()
                competition = match_comp[1].rstrip(')').strip()
            else:
                match = title_text
                competition = "Unknown"

            # Lấy kênh
            channels = []
            provider_links = row.find_all('a', class_='text-stvsProviderLink')
            for link in provider_links:
                channel_name = link.get_text(strip=True)
                if channel_name:
                    channels.append(channel_name)
            if not channels:
                for a in row.find_all('a'):
                    if a.get('href') and 'provider' in a.get('href', ''):
                        name = a.get_text(strip=True)
                        if name:
                            channels.append(name)

            # Lọc giải phù hợp
            competition_lower = competition.lower()
            if any(kw in competition_lower for kw in ["premier league", "serie a", "bundesliga", "la liga", "ligue 1", "uefa champions", "europa league", "conference league"]):
                if "premier" in competition_lower:
                    league = "Premier League"
                elif "serie a" in competition_lower:
                    league = "Serie A"
                elif "bundesliga" in competition_lower:
                    league = "Bundesliga"
                elif "la liga" in competition_lower:
                    league = "La Liga"
                elif "ligue 1" in competition_lower:
                    league = "Ligue 1"
                elif "champions" in competition_lower:
                    league = "UEFA Champions League"
                elif "europa league" in competition_lower:
                    league = "UEFA Europa League"
                elif "conference" in competition_lower:
                    league = "UEFA Europa Conference League"
                else:
                    league = competition
            else:
                continue

            allowed_teams = ALLOWED_TEAMS_PER_LEAGUE.get(league)
            if allowed_teams is not None:
                parts = match.split(' vs ')
                if len(parts) == 2:
                    home_norm = normalize(parts[0])
                    away_norm = normalize(parts[1])
                    if not (any(t in home_norm for t in allowed_teams) or any(t in away_norm for t in allowed_teams)):
                        continue

            games.append({
                "source": "worldsoccertalk",
                "league": league,
                "time": vn_time(kick_utc),
                "match": match,
                "kick_utc": kick_utc,
                "tv_channels": [{"country": "United States", "channels": channels}] if channels else []
            })

    return games

# ================== MATCHS.TV (FR) ==================
async def scrape_matchstv() -> List[Dict]:
    url = "https://matchs.tv/programme-tv/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with AsyncSession() as session:
        resp = await session.get(url, impersonate="chrome120", headers=headers, timeout=30)
        if resp.status_code != 200:
            print("[Matchs.tv] Failed to fetch")
            return []
        html = resp.text

    soup = BeautifulSoup(html, 'lxml')
    games = []
    now_ts = int(datetime.now(TIMEZONE).timestamp())
    max_ts = now_ts + 86400

    tables = soup.find_all('table', class_='programme-tv')
    for table in tables:
        rows = table.find_all('tr')
        current_naive_date = None
        for row in rows:
            h3 = row.find('h3')
            if h3 and h3.find('a'):
                date_text = h3.get_text(strip=True)
                date_parts = date_text.split()
                if len(date_parts) >= 3:
                    day = date_parts[1]
                    month_fr = date_parts[2].lower()
                    month_map = {
                        'janvier': 1, 'février': 2, 'mars': 3, 'avril': 4, 'mai': 5, 'juin': 6,
                        'juillet': 7, 'août': 8, 'septembre': 9, 'octobre': 10, 'novembre': 11, 'décembre': 12
                    }
                    month = month_map.get(month_fr)
                    if month:
                        year = datetime.now().year
                        try:
                            current_naive_date = datetime(year, month, int(day)).date()
                        except:
                            pass
                continue

            time_cell = row.find('td', class_='date')
            if time_cell and current_naive_date:
                time_text = time_cell.get_text(strip=True)
                time_clean = time_text.replace('h', ':')
                try:
                    dt_paris = datetime.combine(current_naive_date, datetime.strptime(time_clean, "%H:%M").time())
                    dt_paris = dt_paris.replace(tzinfo=FR_TIMEZONE)
                    kick_utc = int(dt_paris.timestamp())
                except:
                    continue

                if not (now_ts <= kick_utc <= max_ts):
                    continue

                fixture_cell = row.find('td', class_='fixture')
                if not fixture_cell:
                    continue
                team_link = fixture_cell.find('h4').find('a') if fixture_cell.find('h4') else None
                if team_link:
                    teams_text = team_link.get_text(strip=True)
                else:
                    teams_text = fixture_cell.get_text(strip=True)
                match = teams_text.replace(' - ', ' vs ')

                comp_elem = fixture_cell.find('div', class_='competitions')
                competition = comp_elem.get_text(strip=True) if comp_elem else "Unknown"
                competition = competition.split(',')[0].strip()

                channels = []
                channel_cell = row.find('td', class_='channel')
                if channel_cell:
                    imgs = channel_cell.find_all('img')
                    for img in imgs:
                        title = img.get('title', '')
                        if title:
                            channels.append(title)
                    text = channel_cell.get_text(strip=True)
                    if text and text not in channels:
                        channels.append(text)

                competition_lower = competition.lower()
                if any(kw in competition_lower for kw in ["premier league", "serie a", "bundesliga", "la liga", "ligue 1", "uefa champions", "europa league", "conference league"]):
                    if "premier" in competition_lower:
                        league = "Premier League"
                    elif "serie a" in competition_lower:
                        league = "Serie A"
                    elif "bundesliga" in competition_lower:
                        league = "Bundesliga"
                    elif "la liga" in competition_lower:
                        league = "La Liga"
                    elif "ligue 1" in competition_lower:
                        league = "Ligue 1"
                    elif "champions" in competition_lower:
                        league = "UEFA Champions League"
                    elif "europa league" in competition_lower:
                        league = "UEFA Europa League"
                    elif "conference" in competition_lower:
                        league = "UEFA Europa Conference League"
                    else:
                        league = competition
                else:
                    continue

                allowed_teams = ALLOWED_TEAMS_PER_LEAGUE.get(league)
                if allowed_teams is not None:
                    parts = match.split(' vs ')
                    if len(parts) == 2:
                        home_norm = normalize(parts[0])
                        away_norm = normalize(parts[1])
                        if not (any(t in home_norm for t in allowed_teams) or any(t in away_norm for t in allowed_teams)):
                            continue

                games.append({
                    "source": "matchstv",
                    "league": league,
                    "time": vn_time(kick_utc),
                    "match": match,
                    "kick_utc": kick_utc,
                    "tv_channels": [{"country": "France", "channels": channels}] if channels else []
                })

    return games

# ================== LIVESSOCCERTV (UK top matches) ==================
async def scrape_livesoccertv() -> List[Dict]:
    url = "https://www.livesoccertv.com/schedules/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with AsyncSession() as session:
        resp = await session.get(url, impersonate="chrome120", headers=headers, timeout=30)
        if resp.status_code != 200:
            print("[Livesoccertv] Failed to fetch")
            return []
        html = resp.text

    soup = BeautifulSoup(html, 'lxml')
    games = []
    now_ts = int(datetime.now(TIMEZONE).timestamp())
    max_ts = now_ts + 86400

    fheaders = soup.find_all('div', class_='fheader')
    for fheader in fheaders:
        if "Upcoming Top Matches" in fheader.get_text():
            parent = fheader.find_parent()
            if not parent:
                continue
            found = False
            for sibling in parent.find_all(recursive=False):
                if sibling == fheader:
                    found = True
                    continue
                if not found:
                    continue
                if sibling.name == 'div' and 'fheader' in sibling.get('class', []):
                    break
                spans = sibling.find_all('span', class_='ts')
                for span in spans:
                    dv = span.get('dv')
                    if dv:
                        try:
                            kick_utc = int(dv) // 1000
                        except:
                            continue
                        if not (now_ts <= kick_utc <= max_ts):
                            continue
                        a = sibling.find('a')
                        if a:
                            teams = a.get_text(strip=True)
                            games.append({
                                "source": "livesoccertv",
                                "league": "Top Match",
                                "time": vn_time(kick_utc),
                                "match": teams,
                                "kick_utc": kick_utc,
                                "tv_channels": []
                            })
            break
    return games

# ================== MERGE ==================
def merge_games(all_sources: List[Dict]) -> List[Dict]:
    merged = {}
    for game in all_sources:
        key = (game['league'], game['match'], game['kick_utc'])
        if key not in merged:
            merged[key] = game.copy()
        else:
            existing_channels = merged[key].get('tv_channels', [])
            new_channels = game.get('tv_channels', [])
            for new in new_channels:
                found = False
                for ex in existing_channels:
                    if ex['country'] == new['country']:
                        ex['channels'] = list(set(ex['channels'] + new['channels']))
                        found = True
                        break
                if not found:
                    existing_channels.append(new)
            merged[key]['tv_channels'] = existing_channels
    return list(merged.values())

# ================== MAIN ==================
async def main():
    print("🔄 Bắt đầu lấy lịch 24 GIỜ TỚI từ nhiều nguồn...")
    all_games = []

    # 1. SofaScore
    print("📡 SofaScore...")
    sofascore = await scrape_sofascore()
    save_games("schedule_sofascore.json", sofascore)
    all_games.extend(sofascore)

    # 2. LiveSportsOnTV
    print("📡 LiveSportsOnTV...")
    livesports = await scrape_livesportsontv()
    save_games("schedule_livesportsontv.json", livesports)
    all_games.extend(livesports)

    # 3. WorldSoccerTalk
    print("📡 WorldSoccerTalk...")
    worldsoccertalk = await scrape_worldsoccertalk()
    save_games("schedule_worldsoccertalk.json", worldsoccertalk)
    all_games.extend(worldsoccertalk)

    # 4. Matchs.tv
    print("📡 Matchs.tv...")
    matchstv = await scrape_matchstv()
    save_games("schedule_matchstv.json", matchstv)
    all_games.extend(matchstv)

    # 5. LiveSoccerTV
    print("📡 LiveSoccerTV...")
    livesoccertv = await scrape_livesoccertv()
    save_games("schedule_livesoccertv.json", livesoccertv)
    all_games.extend(livesoccertv)

    # Merge
    print("🔄 Đang merge dữ liệu...")
    merged = merge_games(all_games)
    save_games("schedule_merged.json", merged)
    print(f"✅ Tổng số trận sau merge: {len(merged)}")

if __name__ == "__main__":
    asyncio.run(main())
