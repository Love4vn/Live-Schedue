"""
euro_vn_full_schedule_live.py
================================
BẢN HOÀN CHỈNH – 24 GIỜ TỚI + LỌC THEO GIẢI + ĐỘI RIÊNG
TÍCH HỢP: SofaScore (chính) + Các nguồn JSON phụ (Wheresthematch, LiveSportsOnTV, Ausport)
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

# Danh sách đội riêng từng giải (chỉ áp dụng cho 5 giải lớn)
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
    "Tennis": "Live Tennis",
    "European National Leagues": "Live European",          # Giải vô địch các quốc gia châu Âu
    "FIFA World Cup": "Live Fifa World Cup",               # World Cup
    "International Friendly": "Live International Friendly" # Giao hữu quốc tế
}

# Danh sách quốc gia châu Âu (lấy từ pycountry)
EUROPEAN_COUNTRIES = {c.name.lower() for c in pycountry.countries if c.continent == 'Europe'}
# Danh sách các đội tuyển được phép ngoài châu Âu
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

def vn_time(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC")).astimezone(TIMEZONE)
    return dt.strftime("%d/%m %I:%M %p")

def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def normalize_channel_name(name: str) -> str:
    """Chuẩn hóa tên kênh: loại bỏ từ thừa, cờ, tốc độ, nội dung ngoặc"""
    name = name.lower()
    # Loại bỏ các từ phổ biến
    name = re.sub(r'\b(hd|uhd|4k|fhd|vip|plus|extra|usa|uk|us|tv|channel|network|sports?|premium|maximo?|4mbps|4g|mbps|kbps|bitrate)\b', '', name)
    # Loại bỏ biểu tượng cờ (emoji, ký tự đặc biệt)
    name = re.sub(r'[🇬🇧🇺🇸🇨🇦🇦🇺🇩🇪🇫🇷🇮🇹🇪🇸🇵🇹🇳🇱🇧🇪🇨🇭🇦🇹🇸🇪🇳🇴🇩🇰🇫🇮🇵🇱🇨🇿🇭🇺🇷🇴🇧🇬🇬🇷🇹🇷]', '', name)
    # Loại bỏ nội dung trong ngoặc và dấu ngoặc
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'\[[^\]]*\]', '', name)
    # Loại bỏ ký tự đặc biệt
    name = re.sub(r'[^\w\s]', ' ', name)
    # Chuẩn hóa khoảng trắng
    name = ' '.join(name.split())
    # Bỏ dấu
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ascii')
    return name

def is_channel_match(ch_name: str, m3u_name: str) -> bool:
    """Kiểm tra khớp tên kênh (từ lịch) với tên kênh trong M3U"""
    if not ch_name or not m3u_name:
        return False
    ch_norm = normalize_channel_name(ch_name)
    m3u_norm = normalize_channel_name(m3u_name)
    if len(ch_norm) <= 5:
        return ch_norm == m3u_norm
    if abs(len(ch_norm) - len(m3u_norm)) > 3:
        return False
    return similar(ch_norm, m3u_norm) >= 0.9

def is_team_match(team_name: str, m3u_name: str) -> bool:
    """Kiểm tra xem tên trận (trong M3U) có khớp với đội bóng trong trận đấu không"""
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

def is_european_league(tournament_name: str) -> bool:
    """Kiểm tra giải đấu có phải là giải vô địch quốc gia châu Âu (không thuộc top 5)"""
    # Loại trừ các giải đã xử lý riêng
    excluded = ["premier league", "serie a", "bundesliga", "la liga", "ligue 1", "uefa", "world cup", "friendly"]
    if any(x in tournament_name.lower() for x in excluded):
        return False
    # Kiểm tra nếu tên giải chứa tên quốc gia châu Âu
    for country in EUROPEAN_COUNTRIES:
        if country in tournament_name.lower():
            return True
    return False

def is_friendly_match(home_team: str, away_team: str) -> bool:
    """Kiểm tra trận giao hữu có được phép hay không (dựa trên đội tuyển)"""
    # Lấy tên đội chuẩn hóa
    home_norm = normalize(home_team)
    away_norm = normalize(away_team)
    # Kiểm tra đội tuyển quốc gia (nếu tên đội trùng với tên quốc gia)
    home_country = None
    away_country = None
    for country in pycountry.countries:
        if country.name.lower() == home_norm or country.common_name.lower() == home_norm:
            home_country = country
        if country.name.lower() == away_norm or country.common_name.lower() == away_norm:
            away_country = country
    if home_country and away_country:
        # Cả hai là đội tuyển quốc gia
        if home_country.continent == 'Europe' or away_country.continent == 'Europe':
            return True
        if home_country.name in ALLOWED_NON_EURO_TEAMS or away_country.name in ALLOWED_NON_EURO_TEAMS:
            return True
        return False
    # Nếu không phải đội tuyển quốc gia, có thể là CLB -> không lấy
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

            # Xác định loại giải
            if "premier league" in league_lower:
                league = "Premier League"
                allowed = ALLOWED_TEAMS_PER_LEAGUE[league]
                if allowed and not (any(t in home_team.lower() for t in allowed) or any(t in away_team.lower() for t in allowed)):
                    return None
            elif "serie a" in league_lower:
                league = "Serie A"
                allowed = ALLOWED_TEAMS_PER_LEAGUE[league]
                if allowed and not (any(t in home_team.lower() for t in allowed) or any(t in away_team.lower() for t in allowed)):
                    return None
            elif "bundesliga" in league_lower:
                league = "Bundesliga"
                allowed = ALLOWED_TEAMS_PER_LEAGUE[league]
                if allowed and not (any(t in home_team.lower() for t in allowed) or any(t in away_team.lower() for t in allowed)):
                    return None
            elif "la liga" in league_lower or "laliga" in league_lower:
                league = "La Liga"
                allowed = ALLOWED_TEAMS_PER_LEAGUE[league]
                if allowed and not (any(t in home_team.lower() for t in allowed) or any(t in away_team.lower() for t in allowed)):
                    return None
            elif "ligue 1" in league_lower:
                league = "Ligue 1"
                allowed = ALLOWED_TEAMS_PER_LEAGUE[league]
                if allowed and not (any(t in home_team.lower() for t in allowed) or any(t in away_team.lower() for t in allowed)):
                    return None
            elif "champions" in league_lower:
                league = "UEFA Champions League"
            elif "europa league" in league_lower:
                league = "UEFA Europa League"
            elif "conference" in league_lower:
                league = "UEFA Europa Conference League"
            elif "world cup" in league_lower or "fifa world cup" in league_lower:
                league = "FIFA World Cup"
                # Không lọc đội, lấy tất cả
            elif "friendly" in league_lower or "international friendly" in league_lower:
                league = "International Friendly"
                if not is_friendly_match(home_team, away_team):
                    return None
            elif is_european_league(league_raw):
                league = "European National Leagues"
                # Không lọc đội, lấy tất cả
            else:
                return None  # Không phải giải quan tâm

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
    """Lấy dữ liệu từ SofaScore trong 24 giờ tới"""
    all_games = []
    async with AsyncSession() as session:
        for sport in ["football", "tennis"]:
            now = datetime.now()
            dates = [now.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")]
            now_ts = int(datetime.now(TIMEZONE).timestamp())
            max_ts = now_ts + 86400  # 24 giờ

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
    """Chuyển entry từ schedule_livesportsontv.json sang định dạng chung"""
    try:
        # Ngày tháng: "Date": "2026-03-21"
        # Giờ: "Time": "19:30" (VN)
        dt_str = f"{entry['Date']} {entry['Time']}"
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=TIMEZONE)
        kick_utc = int(dt.timestamp())

        # Tên giải
        league = entry.get('League', '')
        # Matchup: "Liverpool FC @ Brighton & Hove Albion" -> chuyển thành "Liverpool vs Brighton"
        match_raw = entry.get('Matchup', '')
        # Thay @ bằng vs
        match = match_raw.replace(' @ ', ' vs ')
        # Lấy kênh
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
    except:
        return None

def parse_wheresthematch(entry: dict) -> Optional[Dict]:
    """Chuyển entry từ results.json sang định dạng chung"""
    try:
        # "tanggal": "21-03-2026", "time": "22:00"
        day, month, year = entry['tanggal'].split('-')
        time_str = entry['time']
        dt_str = f"{year}-{month}-{day} {time_str}"
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=TIMEZONE)
        kick_utc = int(dt.timestamp())

        league = entry.get('competition', '')
        # title: "Fulham vs Burnley" hoặc home/away
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
    except:
        return None

def parse_ausport(entry: dict) -> Optional[Dict]:
    """Chuyển entry từ ausport_schedule.json sang định dạng chung"""
    try:
        # "vietnam_date": "21/03/2026", "vietnam_time": "19:30"
        day, month, year = entry['vietnam_date'].split('/')
        time_str = entry['vietnam_time']
        dt_str = f"{year}-{month}-{day} {time_str}"
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=TIMEZONE)
        kick_utc = int(dt.timestamp())

        league = entry.get('competition', '')
        home = entry.get('home', '')
        away = entry.get('away', '')
        match = f"{home} vs {away}" if home and away else ''
        # channels có thể là string, tách bằng "|"
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

def load_all_secondary_sources() -> List[Dict]:
    """Đọc tất cả các file JSON phụ và trả về danh sách trận đấu"""
    games = []
    # File livesportsontv
    ls_data = load_json_file("schedule_livesportsontv.json")
    for entry in ls_data:
        g = parse_livesportsontv(entry)
        if g:
            games.append(g)
    # File wheresthematch (results.json)
    wm_data = load_json_file("results.json")
    for entry in wm_data:
        g = parse_wheresthematch(entry)
        if g:
            games.append(g)
    # File ausport
    aus_data = load_json_file("ausport_schedule.json")
    for entry in aus_data:
        g = parse_ausport(entry)
        if g:
            games.append(g)
    return games

# ================== MERGE ==================
def merge_games(primary: List[Dict], secondary: List[Dict]) -> List[Dict]:
    """Merge dữ liệu từ các nguồn phụ vào primary (SofaScore)"""
    # Tạo dict index cho primary theo (league, match normalized, kick_utc gần đúng)
    primary_index = []
    for game in primary:
        norm_match = normalize(game['match'])
        primary_index.append((game, norm_match, game['kick_utc']))

    for sec in secondary:
        sec_norm_match = normalize(sec['match'])
        sec_league = sec['league']
        sec_ts = sec['kick_utc']
        best_match = None
        best_score = 0.0
        for game, norm_match, ts in primary_index:
            # Cùng giải và thời gian chênh lệch <= 1 giờ
            if game['league'] == sec_league and abs(ts - sec_ts) <= 3600:
                score = similar(norm_match, sec_norm_match)
                if score > best_score:
                    best_score = score
                    best_match = game
        if best_match and best_score > 0.7:
            # Gộp kênh
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
            # Không tìm thấy, thêm vào primary
            primary.append(sec)
    return primary

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
    print("🔄 Bắt đầu lấy lịch 24 GIỜ TỚI từ SofaScore và các nguồn JSON phụ...")

    # 1. SofaScore
    print("📡 Đang lấy dữ liệu từ SofaScore...")
    sofascore_games = await scrape_sofascore()
    print(f"   ✅ SofaScore: {len(sofascore_games)} trận")

    # 2. Các nguồn JSON phụ
    print("📡 Đang đọc các nguồn JSON phụ...")
    secondary_games = load_all_secondary_sources()
    print(f"   ✅ Các nguồn phụ: {len(secondary_games)} trận")

    # 3. Merge
    print("🔄 Đang merge dữ liệu...")
    all_games = merge_games(sofascore_games, secondary_games)

    # 4. Lọc trùng và trận đã qua
    seen = {}
    deduped = []
    for g in all_games:
        key = normalize(g["match"]) + "|" + g["time"]
        if key not in seen:
            seen[key] = g
            if datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE) > vn_now:
                deduped.append(g)
    all_games = deduped

    # 5. schedule.json
    today_str = datetime.now().strftime("%Y%m%d")
    schedule = {today_str: {"date": datetime.now().strftime("%A, %d/%m"), "games": all_games}}
    output = {"updated": vn_now.strftime("%Y-%m-%d %H:%M VN"), "days": schedule}
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"✅ schedule.json: {len(all_games)} trận")

    # ================== M3U ==================
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
    seen_urls = set()
    for g in all_games:
        try:
            if datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE) <= vn_now: continue
            # Tìm kênh theo tên kênh
            for tv in g.get("tv_channels", []):
                for ch_name in tv.get("channels", []):
                    matching = [ch for ch in valid_ch if is_channel_match(ch_name, ch['name'])]
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
            # Nếu chưa tìm thấy kênh nào, thử match theo tên trận
            if not any(ev['league'] == g['league'] and ev['name'].startswith(g['time']) for ev in live_events):
                match_norm = normalize(g['match'])
                for ch in valid_ch:
                    if is_team_match(match_norm, ch['name']):
                        url = ch['url']
                        if url in seen_urls: continue
                        seen_urls.add(url)
                        display_name = f"{g['time']} | {g['match']} (M3U: {ch['name']})"
                        live_events.append({
                            "datetime": datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE),
                            "name": display_name,
                            "channel": ch,
                            "league": g["league"]
                        })
                        break  # chỉ lấy một kênh đại diện cho trận này
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
    print(f"   • schedule.json: {len(all_games)} trận")
    print(f"   • live_schedule.m3u: {len(live_events)} kênh (matching thông minh)")

if __name__ == "__main__":
    asyncio.run(main())
