"""
euro_vn_full_schedule_live.py
================================
BẢN HOÀN CHỈNH – 24 GIỜ TỚI + LỌC THEO GIẢI + ĐỘI RIÊNG
TÍCH HỢP: SofaScore (chính) + Các nguồn JSON phụ (Wheresthematch, LiveSportsOnTV, Ausport, FootOnSat)
Tối ưu ghép kênh M3U với matching thông minh (tên kênh + tên trận)
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
from typing import List, Dict, Any, Optional

import pycountry
from curl_cffi.requests import AsyncSession

# ================== CẤU HÌNH ==================
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
UK_TIMEZONE = ZoneInfo("Europe/London")
M3U_LIST_FILE = "M3U_list.txt"
SCHEDULE_FILE = "schedule.json"
LIVE_M3U = "live_schedule.m3u"

# Danh sách giải tennis được phép (ATP và Grand Slam)
ALLOWED_TENNIS_TOURNAMENTS = {
    "atp", "atp tour", "atp world tour", "grand slam", "australian open",
    "roland garros", "french open", "wimbledon", "us open", "nitto atp finals",
    "atp masters", "atp 1000", "atp 500", "atp 250"
}

# Danh sách các giải bóng đá được phép
ALLOWED_FOOTBALL_LEAGUES = {
    "Premier League",
    "Serie A",
    "La Liga",
    "Bundesliga",
    "Ligue 1",
    "UEFA Champions League",
    "UEFA Europa League",
    "UEFA Europa Conference League",
    "UEFA Euro"
}

# Danh sách đội riêng từng giải (tên chuẩn, viết thường)
ALLOWED_TEAMS_PER_LEAGUE = {
    "Premier League": {"arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
                       "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
                       "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
                       "west ham united", "wolverhampton"},
    "Serie A": {"inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"},
    "La Liga": {"barcelona", "real madrid", "atletico madrid"},
    "Bundesliga": {"bayern munich", "borussia dortmund", "bayer leverkusen"},
    "Ligue 1": {"psg", "paris saint-germain", "olympique marseille", "marseille"},
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
    "UEFA Euro": "Live Euro",
    "Tennis": "Live Tennis",
    "FIFA World Cup": "Live Fifa World Cup",
    "International Friendly": "Live International Friendly"
}

# Danh sách các đội tuyển được phép ngoài châu Âu (cho giao hữu)
ALLOWED_NON_EURO_TEAMS = {"argentina", "brazil", "japan", "south korea"}

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

def normalize_team_name(name: str) -> str:
    """Chuẩn hóa tên đội bóng để so sánh với danh sách cho phép"""
    name = unicodedata.normalize("NFKD", name.lower()).encode("ASCII", "ignore").decode("ascii")
    name = re.sub(r'\b(fc|afc|sc|united|city|wanderers|rovers|athletic|albion|town|county)\b', '', name)
    name = re.sub(r'[^\w\s]', ' ', name)
    name = ' '.join(name.split())
    return name

def vn_time(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC")).astimezone(TIMEZONE)
    return dt.strftime("%d/%m %I:%M %p")

def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def normalize_channel_name(name: str) -> str:
    """Chuẩn hóa tên kênh: loại bỏ từ thừa, cờ, tốc độ, nội dung ngoặc, nhưng giữ lại số"""
    name = name.lower()
    # Loại bỏ các từ phổ biến
    name = re.sub(r'\b(hd|uhd|4k|fhd|vip|plus|extra|usa|uk|us|tv|channel|network|sports?|premium|maximo?|4mbps|4g|mbps|kbps|bitrate|stream|live|online)\b', '', name)
    # Loại bỏ biểu tượng cờ
    name = re.sub(r'[🇬🇧🇺🇸🇨🇦🇦🇺🇩🇪🇫🇷🇮🇹🇪🇸🇵🇹🇳🇱🇧🇪🇨🇭🇦🇹🇸🇪🇳🇴🇩🇰🇫🇮🇵🇱🇨🇿🇭🇺🇷🇴🇧🇬🇬🇷🇹🇷]', '', name)
    # Loại bỏ nội dung trong ngoặc
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'\[[^\]]*\]', '', name)
    # Loại bỏ ký tự đặc biệt (giữ lại chữ, số và khoảng trắng)
    name = re.sub(r'[^\w\s]', ' ', name)
    # Chuẩn hóa khoảng trắng
    name = ' '.join(name.split())
    # Bỏ dấu
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ascii')
    return name

def split_name_and_number(name: str):
    """Tách tên kênh thành phần chữ và phần số (nếu có)"""
    match = re.search(r'(\d+)$', name)
    if match:
        number = match.group(1)
        text = name[:match.start()].strip()
        return text, number
    return name, None

def is_channel_match(ch_name: str, m3u_name: str) -> bool:
    if not ch_name or not m3u_name:
        return False
    ch_norm = normalize_channel_name(ch_name)
    m3u_norm = normalize_channel_name(m3u_name)
    
    # Nếu một trong hai quá ngắn (<3), dùng so khớp chính xác
    if len(ch_norm) <= 3 or len(m3u_norm) <= 3:
        return ch_norm == m3u_norm
    
    # Tách số
    ch_text, ch_num = split_name_and_number(ch_norm)
    m3u_text, m3u_num = split_name_and_number(m3u_norm)
    
    # So sánh phần chữ
    text_similarity = similar(ch_text, m3u_text)
    if text_similarity < 0.85:   # Tăng ngưỡng lên 0.85
        return False
    
    # Nếu có số, bắt buộc khớp
    if ch_num is not None and m3u_num is not None:
        return ch_num == m3u_num
    # Nếu chỉ một bên có số, không match
    if ch_num is not None or m3u_num is not None:
        return False
    
    # Nếu không có số, so sánh độ dài và tỷ lệ
    if abs(len(ch_text) - len(m3u_text)) > max(len(ch_text), len(m3u_text)) * 0.3:
        return False
    
    return True

def is_team_match(team_name: str, m3u_name: str) -> bool:
    team_norm = normalize(team_name)
    m3u_norm = normalize_channel_name(m3u_name)
    return similar(team_norm, m3u_norm) >= 0.7

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

def is_uefa_euro(tournament_name: str) -> bool:
    name_lower = tournament_name.lower()
    # Loại bỏ giải trẻ
    if any(x in name_lower for x in ["u19", "u21", "u17", "youth"]):
        return False
    euro_keywords = ["euro", "uefa european championship", "european championship"]
    return any(kw in name_lower for kw in euro_keywords)

def is_uefa_champions(tournament_name: str) -> bool:
    name_lower = tournament_name.lower()
    if "uefa champions league" in name_lower:
        return True
    return False

def is_friendly_match(home_team: str, away_team: str) -> bool:
    home_norm = normalize(home_team)
    away_norm = normalize(away_team)
    home_country = None
    away_country = None
    for country in pycountry.countries:
        if country.name.lower() == home_norm or (hasattr(country, 'common_name') and country.common_name.lower() == home_norm):
            home_country = country
        if country.name.lower() == away_norm or (hasattr(country, 'common_name') and country.common_name.lower() == away_norm):
            away_country = country
    if home_country and away_country:
        european_names = {"albania","andorra","armenia","austria","azerbaijan","belarus","belgium","bosnia and herzegovina","bulgaria","croatia","cyprus","czech republic","denmark","estonia","finland","france","georgia","germany","greece","hungary","iceland","ireland","italy","kazakhstan","kosovo","latvia","liechtenstein","lithuania","luxembourg","malta","moldova","monaco","montenegro","netherlands","north macedonia","norway","poland","portugal","romania","russia","san marino","serbia","slovakia","slovenia","spain","sweden","switzerland","turkey","ukraine","united kingdom","england","scotland","wales","northern ireland"}
        home_in_europe = home_country.name.lower() in european_names
        away_in_europe = away_country.name.lower() in european_names
        if home_in_europe or away_in_europe:
            return True
        if home_country.name.lower() in ALLOWED_NON_EURO_TEAMS or away_country.name.lower() in ALLOWED_NON_EURO_TEAMS:
            return True
        return False
    return False

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
            if not any(keyword in tournament for keyword in ALLOWED_TENNIS_TOURNAMENTS):
                return None
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
        else:  # football
            league_raw = ev.get('tournament', {}).get('name', 'Unknown')
            league_lower = league_raw.lower()
            home_team = ev.get('homeTeam', {}).get('name', '')
            away_team = ev.get('awayTeam', {}).get('name', '')

            # Lọc giải nữ
            if "women" in league_lower or "frauen" in league_lower:
                return None

            # Lọc giải trẻ
            if "u19" in league_lower or "u21" in league_lower or "u17" in league_lower or "youth" in league_lower:
                return None

            if is_uefa_euro(league_raw):
                league = "UEFA Euro"
            elif is_uefa_champions(league_raw):
                league = "UEFA Champions League"
            elif "uefa europa league" in league_lower:
                league = "UEFA Europa League"
            elif "uefa conference league" in league_lower:
                league = "UEFA Europa Conference League"
            elif "premier league" in league_lower:
                home_norm = normalize_team_name(home_team)
                away_norm = normalize_team_name(away_team)
                allowed = ALLOWED_TEAMS_PER_LEAGUE["Premier League"]
                if not (home_norm in allowed or away_norm in allowed):
                    return None
                league = "Premier League"
            elif "serie a" in league_lower:
                home_norm = normalize_team_name(home_team)
                away_norm = normalize_team_name(away_team)
                allowed = ALLOWED_TEAMS_PER_LEAGUE["Serie A"]
                if not (home_norm in allowed or away_norm in allowed):
                    return None
                league = "Serie A"
            elif "bundesliga" in league_lower:
                if "frauen" in league_lower:
                    return None
                home_norm = normalize_team_name(home_team)
                away_norm = normalize_team_name(away_team)
                allowed = ALLOWED_TEAMS_PER_LEAGUE["Bundesliga"]
                if not (home_norm in allowed or away_norm in allowed):
                    return None
                league = "Bundesliga"
            elif "la liga" in league_lower or "laliga" in league_lower:
                home_norm = normalize_team_name(home_team)
                away_norm = normalize_team_name(away_team)
                allowed = ALLOWED_TEAMS_PER_LEAGUE["La Liga"]
                if not (home_norm in allowed or away_norm in allowed):
                    return None
                league = "La Liga"
            elif "ligue 1" in league_lower:
                home_norm = normalize_team_name(home_team)
                away_norm = normalize_team_name(away_team)
                allowed = ALLOWED_TEAMS_PER_LEAGUE["Ligue 1"]
                if not (home_norm in allowed or away_norm in allowed):
                    return None
                league = "Ligue 1"
            elif "world cup" in league_lower or "fifa world cup" in league_lower:
                league = "FIFA World Cup"
            elif "friendly" in league_lower or "international friendly" in league_lower:
                league = "International Friendly"
                if not is_friendly_match(home_team, away_team):
                    return None
            else:
                return None

            if league not in ALLOWED_FOOTBALL_LEAGUES and league not in ["FIFA World Cup", "International Friendly"]:
                return None

            match = f"{home_team} vs {away_team}"
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
            dates = [now.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")]
            now_ts = int(datetime.now(TIMEZONE).timestamp())
            max_ts = now_ts + 86400

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

# ================== ĐỌC CÁC NGUỒN JSON PHỤ ==================
def load_json_file(filename: str) -> list:
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def parse_livesportsontv(entry: dict) -> Optional[Dict]:
    try:
        dt_str = f"{entry['Date']} {entry['Time']}"
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=TIMEZONE)
        kick_utc = int(dt.timestamp())

        league = entry.get('League', '')
        # Xử lý tennis
        if "Tennis" in league:
            league = "Tennis"
        else:
            if "Premier League" in league:
                league = "Premier League"
            elif "Serie A" in league:
                league = "Serie A"
            elif "Bundesliga" in league:
                league = "Bundesliga"
            elif "La Liga" in league:
                league = "La Liga"
            elif "Ligue 1" in league:
                league = "Ligue 1"
            elif "UEFA Champions League" in league:
                league = "UEFA Champions League"
            elif "UEFA Europa League" in league:
                league = "UEFA Europa League"
            elif "UEFA Europa Conference League" in league:
                league = "UEFA Europa Conference League"
            elif "Euro" in league:
                league = "UEFA Euro"
            else:
                return None

        if league not in ALLOWED_FOOTBALL_LEAGUES and league != "Tennis":
            return None

        match_raw = entry.get('Matchup', '')
        match = match_raw.replace(' @ ', ' vs ')
        channels = entry.get('Services', [])
        if not channels:
            return None

        return {
            "league": league,
            "match": match,
            "kick_utc": kick_utc,
            "time": vn_time(kick_utc),
            "tv_channels": [{"country": "LiveSportsOnTV", "channels": channels}],
            "source": "livesportsontv"
        }
    except Exception as e:
        print(f"   Lỗi parse livesportsontv: {e}")
        return None

def parse_wheresthematch(entry: dict) -> Optional[Dict]:
    try:
        day, month, year = entry['tanggal'].split('-')
        time_str = entry['time']
        dt_str = f"{year}-{month}-{day} {time_str}"
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=TIMEZONE)
        kick_utc = int(dt.timestamp())

        league = entry.get('competition', '')
        sport = entry.get('sport', '')
        # Xử lý tennis
        if sport == "Tennis" or "Tennis" in league:
            league = "Tennis"
        else:
            if "Premier League" in league:
                league = "Premier League"
            elif "Serie A" in league:
                league = "Serie A"
            elif "Bundesliga" in league:
                league = "Bundesliga"
            elif "La Liga" in league:
                league = "La Liga"
            elif "Ligue 1" in league:
                league = "Ligue 1"
            elif "UEFA Champions League" in league:
                league = "UEFA Champions League"
            elif "UEFA Europa League" in league:
                league = "UEFA Europa League"
            elif "UEFA Europa Conference League" in league:
                league = "UEFA Europa Conference League"
            elif "Euro" in league:
                league = "UEFA Euro"
            else:
                return None

        if league not in ALLOWED_FOOTBALL_LEAGUES and league != "Tennis":
            return None

        match = entry.get('title', '')
        if not match:
            home = entry.get('home', '')
            away = entry.get('away', '')
            match = f"{home} vs {away}" if home and away else ''
        channels = entry.get('channels', [])
        if not channels:
            return None

        return {
            "league": league,
            "match": match,
            "kick_utc": kick_utc,
            "time": vn_time(kick_utc),
            "tv_channels": [{"country": "Wheresthematch", "channels": channels}],
            "source": "wheresthematch"
        }
    except Exception as e:
        print(f"   Lỗi parse wheresthematch: {e}")
        return None

def parse_ausport(entry: dict) -> Optional[Dict]:
    try:
        day, month, year = entry['vietnam_date'].split('/')
        time_str = entry['vietnam_time']
        dt_str = f"{year}-{month}-{day} {time_str}"
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=TIMEZONE)
        kick_utc = int(dt.timestamp())

        league = entry.get('competition', '')
        if "Premier League" in league:
            league = "Premier League"
        elif "Serie A" in league:
            league = "Serie A"
        elif "Bundesliga" in league:
            league = "Bundesliga"
        elif "La Liga" in league:
            league = "La Liga"
        elif "Ligue 1" in league:
            league = "Ligue 1"
        elif "UEFA Champions League" in league:
            league = "UEFA Champions League"
        elif "UEFA Europa League" in league:
            league = "UEFA Europa League"
        elif "UEFA Europa Conference League" in league:
            league = "UEFA Europa Conference League"
        elif "ATP" in league or "WTA" in league:
            league = "Tennis"
        elif "Euro" in league:
            league = "UEFA Euro"
        else:
            return None

        if league not in ALLOWED_FOOTBALL_LEAGUES and league != "Tennis":
            return None

        home = entry.get('home', '')
        away = entry.get('away', '')
        match = f"{home} vs {away}" if home and away else ''
        channels_str = entry.get('channels', '')
        channels = [ch.strip() for ch in channels_str.split('|')] if channels_str else []
        if not channels:
            return None

        return {
            "league": league,
            "match": match,
            "kick_utc": kick_utc,
            "time": vn_time(kick_utc),
            "tv_channels": [{"country": "Ausport", "channels": channels}],
            "source": "ausport"
        }
    except:
        return None

# ================== FOOTONSAT ==================
def download_footonsat() -> dict:
    url = "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/premierleague.json"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data
    except Exception as e:
        print(f"   Lỗi tải footonsat: {e}")
        return None

def parse_footonsat(entry: dict) -> Optional[Dict]:
    try:
        if 'compet' in entry and 'match' in entry:
            compet = entry.get('compet', '')
            if "Premier League" not in compet:
                return None
            match = entry.get('match', '').strip()
            if not match:
                return None
            date_str = entry.get('date')
            time_str = entry.get('time')
            if not date_str or not time_str:
                return None
            # Giả sử time_str là giờ UTC (kém VN 7h)
            dt_utc = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            dt_utc = dt_utc.replace(tzinfo=ZoneInfo("UTC"))
            kick_utc = int(dt_utc.timestamp())
            return {
                "type": "match",
                "match": match,
                "kick_utc": kick_utc,
                "time": vn_time(kick_utc),
                "date": date_str,
                "time_str": time_str
            }
        elif 'channel' in entry and 'related_to' in entry:
            channel = entry.get('channel', '').strip()
            related_to = entry.get('related_to', '').strip()
            if not channel or not related_to:
                return None
            return {
                "type": "channel",
                "channel": channel,
                "related_to": related_to
            }
        return None
    except Exception as e:
        return None

def load_footonsat_data(now_ts: int, max_ts: int) -> List[Dict]:
    games = []
    data = download_footonsat()
    if not data or 'footonsat' not in data:
        return games

    matches = {}
    channels_by_match = {}

    for item in data['footonsat']:
        parsed = parse_footonsat(item)
        if not parsed:
            continue
        if parsed['type'] == 'match':
            if now_ts <= parsed['kick_utc'] <= max_ts:
                match_name = parsed['match']
                date = parsed['date']
                key = (match_name, date)
                matches[key] = parsed
        elif parsed['type'] == 'channel':
            related = parsed['related_to']
            if related not in channels_by_match:
                channels_by_match[related] = []
            channels_by_match[related].append(parsed['channel'])

    for key, match in matches.items():
        match_name = match['match']
        channels = channels_by_match.get(match_name, [])
        if channels:
            channels = list(set(channels))
            games.append({
                "league": "Premier League",
                "match": match_name,
                "kick_utc": match['kick_utc'],
                "time": match['time'],
                "tv_channels": [{"country": "FootOnSat", "channels": channels}],
                "source": "footonsat"
            })
    return games

def load_all_secondary_sources(now_ts: int, max_ts: int) -> List[Dict]:
    games = []
    # LiveSportsOnTV
    ls_data = load_json_file("schedule_livesportsontv.json")
    for entry in ls_data:
        g = parse_livesportsontv(entry)
        if g and now_ts <= g['kick_utc'] <= max_ts:
            games.append(g)
    # Wheresthematch
    wm_data = load_json_file("results.json")
    for entry in wm_data:
        g = parse_wheresthematch(entry)
        if g and now_ts <= g['kick_utc'] <= max_ts:
            games.append(g)
    # Ausport
    aus_data = load_json_file("ausport_schedule.json")
    for entry in aus_data:
        g = parse_ausport(entry)
        if g and now_ts <= g['kick_utc'] <= max_ts:
            games.append(g)
    # FootOnSat
    footonsat_games = load_footonsat_data(now_ts, max_ts)
    games.extend(footonsat_games)
    return games

# ================== MERGE ==================
def merge_games(primary: List[Dict], secondary: List[Dict]) -> List[Dict]:
    primary_football = [g for g in primary if g['league'] != "Tennis"]
    primary_tennis = [g for g in primary if g['league'] == "Tennis"]
    secondary_football = [g for g in secondary if g['league'] != "Tennis"]
    secondary_tennis = [g for g in secondary if g['league'] == "Tennis"]

    # Merge football
    primary_index = [(game, normalize(game['match']), game['kick_utc']) for game in primary_football]
    for sec in secondary_football:
        sec_norm_match = normalize(sec['match'])
        sec_league = sec['league']
        sec_ts = sec['kick_utc']
        best_match = None
        best_score = 0.0
        for game, norm_match, ts in primary_index:
            if game['league'] == sec_league and abs(ts - sec_ts) <= 3600:
                score = similar(norm_match, sec_norm_match)
                if score > best_score:
                    best_score = score
                    best_match = game
        if best_match and best_score > 0.7:
            for sec_ch in sec['tv_channels']:
                found = False
                for pri_ch in best_match['tv_channels']:
                    if pri_ch['country'] == sec_ch['country']:
                        pri_ch['channels'] = list(set(pri_ch['channels'] + sec_ch['channels']))
                        found = True
                        break
                if not found:
                    best_match['tv_channels'].append(sec_ch)
        else:
            primary_football.append(sec)

    # Tennis: không merge, chỉ thêm tất cả
    all_tennis = primary_tennis + secondary_tennis
    seen = {}
    unique_tennis = []
    for g in all_tennis:
        key = (g['kick_utc'], g['match']) if g['match'] else (g['kick_utc'], g.get('source', ''))
        if key not in seen:
            seen[key] = g
            unique_tennis.append(g)
        else:
            # Gộp kênh cho tennis trùng thời gian
            for sec_ch in g['tv_channels']:
                found = False
                for pri_ch in seen[key]['tv_channels']:
                    if pri_ch['country'] == sec_ch['country']:
                        pri_ch['channels'] = list(set(pri_ch['channels'] + sec_ch['channels']))
                        found = True
                        break
                if not found:
                    seen[key]['tv_channels'].append(sec_ch)

    return primary_football + unique_tennis

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
    now_ts = int(datetime.now(TIMEZONE).timestamp())
    max_ts = now_ts + 86400

    print("🔄 Bắt đầu lấy lịch 24 GIỜ TỚI từ SofaScore và các nguồn JSON phụ...")

    print("📡 Đang lấy dữ liệu từ SofaScore...")
    sofascore_games = await scrape_sofascore()
    print(f"   ✅ SofaScore: {len(sofascore_games)} trận")

    print("📡 Đang đọc các nguồn JSON phụ...")
    secondary_games = load_all_secondary_sources(now_ts, max_ts)
    print(f"   ✅ Các nguồn phụ: {len(secondary_games)} trận")

    print("🔄 Đang merge dữ liệu...")
    all_games = merge_games(sofascore_games, secondary_games)

    seen = {}
    deduped = []
    for g in all_games:
        if g['league'] == "Tennis" and not g['match']:
            key = (g['kick_utc'], g['league'])
        else:
            key = normalize(g["match"]) + "|" + g["time"] if g["match"] else g["time"] + "|" + str(g["kick_utc"])
        if key not in seen:
            seen[key] = g
            if datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE) > vn_now:
                deduped.append(g)
        else:
            # Gộp kênh cho tennis cùng thời gian
            if g['league'] == "Tennis" and not g['match']:
                for sec_ch in g['tv_channels']:
                    found = False
                    for pri_ch in seen[key]['tv_channels']:
                        if pri_ch['country'] == sec_ch['country']:
                            pri_ch['channels'] = list(set(pri_ch['channels'] + sec_ch['channels']))
                            found = True
                            break
                    if not found:
                        seen[key]['tv_channels'].append(sec_ch)
    all_games = deduped

    today_str = datetime.now().strftime("%Y%m%d")
    schedule = {today_str: {"date": datetime.now().strftime("%A, %d/%m"), "games": all_games}}
    output = {"updated": vn_now.strftime("%Y-%m-%d %H:%M VN"), "days": schedule}
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"✅ schedule.json: {len(all_games)} trận")

    print("📥 Đang lọc kênh M3U (matching thông minh)...")
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
    for g in all_games:
        try:
            if datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE) <= vn_now: continue
            used_urls_in_match = set()
            for tv in g.get("tv_channels", []):
                for ch_name in tv.get("channels", []):
                    matching = [ch for ch in valid_ch if is_channel_match(ch_name, ch['name'])]
                    for ch in matching:
                        url = ch['url']
                        if url in used_urls_in_match: continue
                        used_urls_in_match.add(url)
                        display_name = f"{g['time']} | {g['match']} ({ch_name})"
                        live_events.append({
                            "datetime": datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE),
                            "name": display_name,
                            "channel": ch,
                            "league": g["league"]
                        })
            if not used_urls_in_match and g['match']:
                match_norm = normalize(g['match'])
                for ch in valid_ch:
                    if is_team_match(match_norm, ch['name']):
                        url = ch['url']
                        if url in used_urls_in_match: continue
                        used_urls_in_match.add(url)
                        display_name = f"{g['time']} | {g['match']} (M3U: {ch['name']})"
                        live_events.append({
                            "datetime": datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE),
                            "name": display_name,
                            "channel": ch,
                            "league": g["league"]
                        })
                        break
        except:
            continue

    # Xử lý tennis: nhóm theo kênh và league, chỉ giữ một entry mỗi kênh
    tennis_events = [ev for ev in live_events if ev['league'] == "Tennis"]
    other_events = [ev for ev in live_events if ev['league'] != "Tennis"]
    grouped_tennis = {}
    for ev in tennis_events:
        key = (ev['channel']['url'], ev['league'])
        if key not in grouped_tennis:
            grouped_tennis[key] = ev
    tennis_events_dedup = list(grouped_tennis.values())
    live_events = other_events + tennis_events_dedup
    live_events.sort(key=lambda x: x["datetime"])

    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ev in live_events:
            ch = ev["channel"]
            group_title = LEAGUE_GROUP_NAME.get(ev["league"], None)
            if not group_title:
                continue
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
    print(f"   • schedule.json: {len(all_games)} trận")
    print(f"   • live_schedule.m3u: {len(live_events)} kênh (matching thông minh)")

if __name__ == "__main__":
    asyncio.run(main())
