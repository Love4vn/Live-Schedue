"""
euro_vn_full_schedule_live.py
================================
BẢN HOÀN CHỈNH – 48 GIỜ TỚI + LỌC THEO GIẢI + ĐỘI RIÊNG
TÍCH HỢP: SofaScore, Where's The Match, LiveSportsOnTV
Xuất file riêng cho từng nguồn, sau đó merge
"""

import asyncio
import json
import re
import unicodedata
import urllib.request
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote
from difflib import SequenceMatcher
from typing import List, Dict, Any

import pycountry
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ================== CẤU HÌNH ==================
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
UK_TIMEZONE = ZoneInfo("Europe/London")
M3U_LIST_FILE = "M3U_list.txt"
SCHEDULE_FILE = "schedule.json"
LIVE_M3U = "live_schedule.m3u"
SOURCE_OUTPUT_DIR = "."

# DANH SÁCH ĐỘI RIÊNG TỪNG GIẢI
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

LEAGUE_GROUP_NAME = {
    "Premier League": "Live Premier League",
    "Serie A": "Live Serie A",
    "Bundesliga": "Live Bundesliga",
    "La Liga": "Live La Liga",
    "Ligue 1": "Live Ligue 1",
    "UEFA Champions League": "Live UEFA Champions League",
    "UEFA Europa League": "Live UEFA Europa League",
    "UEFA Europa Conference League": "Live UEFA Conference League",
    "Tennis": "Live Tennis"
}

# ================== HELPER ==================
def fetch_text_sync(url: str, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; EuroVN/9.0)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8")
    except:
        return ""

def is_healthy(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "VLC/3.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            return r.getcode() < 400
    except:
        return False

def is_low_resolution(name: str) -> bool:
    n = name.lower()
    return any(x in n for x in ["sd", "360p", "480p", "576p", "low res", "low quality"])

def normalize(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return " ".join(c for c in s if unicodedata.category(c) != "Mn")

def vn_time(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC")).astimezone(TIMEZONE)
    return dt.strftime("%d/%m %I:%M %p")

def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def save_source_games(source_name: str, games: List[Dict]):
    filename = f"{SOURCE_OUTPUT_DIR}/schedule_{source_name}.json"
    output = {
        "source": source_name,
        "updated": datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M VN"),
        "games": games
    }
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"   ✅ Đã lưu {len(games)} trận từ {source_name} vào {filename}")

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
            league = "Tennis"
            match = f"{ev.get('homeTeam', {}).get('name', '')} vs {ev.get('awayTeam', {}).get('name', '')}"
            return {
                "league": league,
                "time": vn_time(start_ts),
                "match": match,
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

            match = f"{ev.get('homeTeam', {}).get('name', '')} vs {ev.get('awayTeam', {}).get('name', '')}"
            return {
                "league": league,
                "time": vn_time(start_ts),
                "match": match,
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
            dates = [now.strftime("%Y-%m-%d"), 
                     (now + timedelta(days=1)).strftime("%Y-%m-%d"),
                     (now + timedelta(days=2)).strftime("%Y-%m-%d")]
            now_ts = int(datetime.now(TIMEZONE).timestamp())
            max_ts = now_ts + 172800

            for date_str in dates:
                url = f"https://www.sofascore.com/api/v1/sport/{sport}/scheduled-events/{date_str}"
                res = await session.get(url, impersonate="chrome120", timeout=30)
                if res.status_code != 200: continue
                events = res.json().get('events', [])
                tasks = [fetch_sofascore_event(session, e['id'], sport, now_ts, max_ts) for e in events]
                results = await asyncio.gather(*tasks)
                all_games.extend([r for r in results if r])
            await asyncio.sleep(2)
    return all_games

# ================== WHERE'S THE MATCH (Dùng Playwright) ==================
async def scrape_wtm() -> List[Dict]:
    url = "https://www.wheresthematch.com/live-football-on-tv/"
    fixtures = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=30000)
            await page.wait_for_selector('tr[itemscope][itemtype*="BroadcastEvent"]', timeout=10000)
            html = await page.content()
        except Exception as e:
            print(f"[WTM] Lỗi khi tải trang: {e}")
            return []
        finally:
            await browser.close()

    # Parse HTML với BeautifulSoup
    fixtures = _parse_wtm_html(html)

    # Lọc trong 48h
    now_ts = int(datetime.now(TIMEZONE).timestamp())
    max_ts = now_ts + 172800
    filtered = [f for f in fixtures if now_ts <= f['kickoff_utc'] <= max_ts]
    return filtered

def _parse_wtm_html(html: str) -> list:
    soup = BeautifulSoup(html, 'lxml')
    rows = soup.select('tr[itemscope][itemtype*="BroadcastEvent"]')
    fixtures = []

    for row in rows:
        if re.search(r"women'?s|womens|ladies", row.get_text(), re.I):
            continue

        team_links = row.select('td.fixture-details a[title]')
        home = away = None
        if len(team_links) >= 2:
            home = team_links[0].get('title') or team_links[0].text.strip()
            away = team_links[-1].get('title') or team_links[-1].text.strip()
        else:
            fixture_cell = row.select_one('td.fixture-details')
            if fixture_cell:
                text = fixture_cell.get_text(strip=True)
                m = re.search(r'(.+?)\s+(?:v|vs|versus|–|-)\s+(.+)', text, re.I)
                if m:
                    home, away = m.groups()
        if not home or not away:
            continue
        home = home.strip()
        away = away.strip()

        kickoff_utc = None
        meta = row.select_one('td.start-details meta[itemprop="startDate"]')
        if meta and meta.get('content'):
            iso = meta['content']
            try:
                if iso.endswith('Z'):
                    iso = iso.replace('Z', '+00:00')
                dt = datetime.fromisoformat(iso)
                kickoff_utc = int(dt.timestamp())
            except:
                pass
        if not kickoff_utc:
            continue

        comp_elem = row.select_one('td.competition-name span')
        if comp_elem:
            competition = comp_elem.text.strip()
        else:
            comp_elem = row.select_one('td.competition-name')
            competition = comp_elem.text.strip() if comp_elem else ""

        channels = set()
        imgs = row.select('td.channel-details img')
        for img in imgs:
            alt = img.get('alt', '').strip()
            title = img.get('title', '').strip()
            name = alt or title
            if name:
                name = re.sub(r'\s+logo$', '', name, flags=re.I).strip()
                channels.add(name)
        chan_cell = row.select_one('td.channel-details')
        if chan_cell:
            text = chan_cell.get_text(separator=' ', strip=True)
            if text:
                for part in re.split(r'[,;]', text):
                    part = part.strip()
                    if part and not any(x in part.lower() for x in ['logo', 'image']):
                        channels.add(part)

        fixtures.append({
            'home': home,
            'away': away,
            'kickoff_utc': kickoff_utc,
            'competition': competition,
            'channels': list(channels)
        })

    return fixtures

# ================== LIVESPORTSONTV (Playwright) ==================
LIVESPORTS_SPORTS = {
    "football": {
        "EPL": "https://www.livesportsontv.com/league/english-premier-league",
        "LaLiga": "https://www.livesportsontv.com/league/la-liga",
        "Bundesliga": "https://www.livesportsontv.com/league/bundesliga",
        "SerieA": "https://www.livesportsontv.com/league/serie-a",
        "Ligue1": "https://www.livesportsontv.com/league/ligue-1",
        "UCL": "https://www.livesportsontv.com/league/uefa-champions-league",
        "UEL": "https://www.livesportsontv.com/league/uefa-europa-league",
        "UECL": "https://www.livesportsontv.com/league/uefa-europa-conference-league",
    },
    "tennis": {
        "ATP": "https://www.livesportsontv.com/sport/tennis/atp",
        "WTA": "https://www.livesportsontv.com/sport/tennis/wta",
    }
}

async def scrape_livesportsontv() -> List[Dict]:
    all_games = []
    now_ts = int(datetime.now(TIMEZONE).timestamp())
    max_ts = now_ts + 172800

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for sport, leagues in LIVESPORTS_SPORTS.items():
            for league_name, url in leagues.items():
                print(f"   [LiveSports] Đang xử lý {league_name}...")
                try:
                    await page.goto(url, timeout=30000)
                    await page.wait_for_selector('div.event--wrapp', timeout=10000)
                    for _ in range(3):
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await page.wait_for_timeout(1000)

                    html = await page.content()
                    soup = BeautifulSoup(html, 'lxml')
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
                                dt_str = f"{day} {month} {year} {time_str}"
                                dt_obj = datetime.strptime(dt_str, "%d %b %Y %H:%M")
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

                            channels = []
                            channel_list = row.find('ul', class_='event__tags')
                            if channel_list:
                                for channel_link in channel_list.find_all('a'):
                                    channel_name = channel_link.get('aria-label')
                                    if channel_name:
                                        channels.append(channel_name)

                            if sport == "tennis":
                                league = "Tennis"
                            else:
                                league_map = {
                                    "EPL": "Premier League",
                                    "LaLiga": "La Liga",
                                    "Bundesliga": "Bundesliga",
                                    "SerieA": "Serie A",
                                    "Ligue1": "Ligue 1",
                                    "UCL": "UEFA Champions League",
                                    "UEL": "UEFA Europa League",
                                    "UECL": "UEFA Europa Conference League",
                                }
                                league = league_map.get(league_name, league_name)

                            all_games.append({
                                "league": league,
                                "time": vn_time(kick_utc),
                                "match": match,
                                "kick_utc": kick_utc,
                                "tv_channels": [{"country": "United Kingdom", "channels": channels}] if channels else [],
                                "source": "livesportsontv"
                            })
                        except Exception as e:
                            continue
                except Exception as e:
                    print(f"   [LiveSports] Lỗi khi xử lý {league_name}: {e}")
                    continue

        await browser.close()
    return all_games

# ================== MERGE ==================
def merge_games(sofascore_games: List[Dict], wtm_games: List[Dict], livesports_games: List[Dict]) -> List[Dict]:
    # Tạo index cho tennis (dùng tournament + thời gian)
    tennis_index = {}
    for game in sofascore_games:
        if game['league'] == 'Tennis':
            key = (game.get('tournament', ''), game['kick_utc'])
            tennis_index[key] = game

    # Merge WTM (football)
    for wtm in wtm_games:
        best_match = None
        best_score = 0.0
        for game in sofascore_games:
            if game['league'] == 'Tennis':
                continue
            parts = game['match'].split(' vs ')
            if len(parts) != 2:
                continue
            sof_home = normalize(parts[0])
            sof_away = normalize(parts[1])
            wtm_home = normalize(wtm['home'])
            wtm_away = normalize(wtm['away'])
            score_home = similar(sof_home, wtm_home)
            score_away = similar(sof_away, wtm_away)
            avg_score = (score_home + score_away) / 2
            time_diff = abs(game['kick_utc'] - wtm['kickoff_utc'])
            if avg_score > best_score and time_diff < 3600:
                best_score = avg_score
                best_match = game
        if best_match and best_score > 0.7:
            uk_channels = wtm['channels']
            if uk_channels:
                found = False
                for tv in best_match['tv_channels']:
                    if tv['country'] == 'United Kingdom':
                        tv['channels'] = list(set(tv['channels'] + uk_channels))
                        found = True
                        break
                if not found:
                    best_match['tv_channels'].append({
                        'country': 'United Kingdom',
                        'channels': uk_channels
                    })

    # Merge LiveSports
    for ls in livesports_games:
        if ls['league'] == 'Tennis':
            for game in sofascore_games:
                if game['league'] == 'Tennis' and abs(game['kick_utc'] - ls['kick_utc']) < 3600:
                    if ls['tv_channels'] and ls['tv_channels'][0]['channels']:
                        found = False
                        for tv in game['tv_channels']:
                            if tv['country'] == 'United Kingdom':
                                tv['channels'] = list(set(tv['channels'] + ls['tv_channels'][0]['channels']))
                                found = True
                                break
                        if not found:
                            game['tv_channels'].append({
                                'country': 'United Kingdom',
                                'channels': ls['tv_channels'][0]['channels']
                            })
                    break
        else:
            parts = ls['match'].split(' vs ')
            if len(parts) != 2:
                continue
            ls_home = normalize(parts[0])
            ls_away = normalize(parts[1])
            best_match = None
            best_score = 0.0
            for game in sofascore_games:
                if game['league'] == 'Tennis':
                    continue
                sof_parts = game['match'].split(' vs ')
                if len(sof_parts) != 2:
                    continue
                sof_home = normalize(sof_parts[0])
                sof_away = normalize(sof_parts[1])
                score_home = similar(sof_home, ls_home)
                score_away = similar(sof_away, ls_away)
                avg_score = (score_home + score_away) / 2
                time_diff = abs(game['kick_utc'] - ls['kick_utc'])
                if avg_score > best_score and time_diff < 3600:
                    best_score = avg_score
                    best_match = game
            if best_match and best_score > 0.7:
                uk_channels = ls['tv_channels'][0]['channels'] if ls['tv_channels'] else []
                if uk_channels:
                    found = False
                    for tv in best_match['tv_channels']:
                        if tv['country'] == 'United Kingdom':
                            tv['channels'] = list(set(tv['channels'] + uk_channels))
                            found = True
                            break
                    if not found:
                        best_match['tv_channels'].append({
                            'country': 'United Kingdom',
                            'channels': uk_channels
                        })

    return sofascore_games

# ================== M3U PARSER ==================
def parse_m3u(content):
    channels = []
    current = {}
    extra = []
    for line in content.split('\n'):
        line = line.strip()
        if not line: continue
        if line.startswith('#EXTINF'):
            if current.get('name') and current.get('url'):
                if extra: current['extra'] = extra[:]
                channels.append(current)
            current = {}
            extra = []
            params = re.findall(r'([a-zA-Z-]+)="([^"]*)"', line)
            current['params'] = {k.lower(): v for k,v in params}
            name_part = line.split(',', 1)
            current['name'] = unquote(name_part[1].strip()) if len(name_part)>1 else "Unknown"
        elif line.startswith('http'):
            if current:
                current['url'] = line
                if extra: current['extra'] = extra[:]
                channels.append(current)
                current = {}
                extra = []
        elif line.startswith('#'):
            extra.append(line)
    if current.get('name') and current.get('url'):
        if extra: current['extra'] = extra[:]
        channels.append(current)
    return channels

# ================== MAIN ==================
async def main():
    start = time.time()
    vn_now = datetime.now(TIMEZONE)
    print("🔄 Bắt đầu lấy lịch 48 GIỜ TỚI từ nhiều nguồn...")

    # 1. SofaScore
    print("📡 Đang lấy dữ liệu từ SofaScore...")
    sofascore_games = await scrape_sofascore()
    save_source_games("sofascore", sofascore_games)

    # 2. Where's The Match
    print("📡 Đang lấy dữ liệu từ Where's The Match...")
    wtm_games = await scrape_wtm()
    save_source_games("wtm", wtm_games)

    # 3. LiveSportsOnTV
    print("📡 Đang lấy dữ liệu từ LiveSportsOnTV...")
    livesports_games = await scrape_livesportsontv()
    save_source_games("livesportsontv", livesports_games)

    # 4. Merge
    print("🔄 Đang merge dữ liệu từ các nguồn...")
    merged_games = merge_games(sofascore_games, wtm_games, livesports_games)

    # 5. schedule.json
    today_str = datetime.now().strftime("%Y%m%d")
    schedule = {today_str: {"date": datetime.now().strftime("%A, %d/%m"), "games": merged_games}}
    day = schedule[today_str]

    seen = {}
    deduped = []
    for g in day["games"]:
        key = normalize(g["match"]) + "|" + g["time"]
        if key not in seen:
            seen[key] = g
            deduped.append(g)
    day["games"] = [g for g in deduped if datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE) > vn_now]

    output = {"updated": vn_now.strftime("%Y-%m-%d %H:%M VN"), "days": schedule}
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"✅ schedule.json: {len(day['games'])} trận")

    # 6. M3U
    print("📥 Đang lọc kênh M3U...")
    m3u_links = [line.strip() for line in open(M3U_LIST_FILE, encoding='utf-8') if line.strip().startswith('http')]

    all_ch = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(lambda u: (u, fetch_text_sync(u)), url): url for url in m3u_links}
        for fut in as_completed(futures):
            try:
                _, content = fut.result()
                chs = parse_m3u(content)
                for ch in chs:
                    if is_low_resolution(ch.get('name', '')): continue
                    all_ch.append(ch)
            except:
                continue

    unique_ch = list({ch['url']: ch for ch in all_ch if ch.get('url')}.values())
    valid_ch = [ch for ch in unique_ch if is_healthy(ch['url'])]

    live_events = []
    seen_urls = set()
    for g in day["games"]:
        try:
            if datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE) <= vn_now: continue
            for tv in g.get("tv_channels", []):
                for ch_name in tv.get("channels", []):
                    matching = [ch for ch in valid_ch if ch_name.lower() in ch['name'].lower()]
                    for ch in matching:
                        url = ch['url']
                        if url in seen_urls: continue
                        seen_urls.add(url)
                        display_name = f"{g['time']} | {g['match']} ({ch_name})"
                        live_events.append({
                            "datetime": datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE),
                            "name": display_name,
                            "channel": ch,
                            "league": g["league"]
                        })
        except:
            continue

    live_events.sort(key=lambda x: x["datetime"])

    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ev in live_events:
            ch = ev["channel"]
            group_title = LEAGUE_GROUP_NAME.get(ev["league"], "Live Other")
            extinf = f'#EXTINF:-1 tvg-id="{ch["params"].get("tvg-id","")}" group-title="{group_title}"'
            if ch["params"].get("tvg-logo"):
                extinf += f' tvg-logo="{ch["params"]["tvg-logo"]}"'
            extinf += f',{ev["name"]}'
            f.write(extinf + "\n")
            if 'extra' in ch:
                for line in ch['extra']:
                    if not line.startswith('#EXTINF'):
                        f.write(line + "\n")
            f.write(ch['url'] + "\n")

    elapsed = time.time() - start
    print(f"\n🎉 HOÀN THÀNH!")
    print(f"   • schedule.json: {len(day['games'])} trận")
    print(f"   • live_schedule.m3u: {len(live_events)} kênh")

if __name__ == "__main__":
    asyncio.run(main())
