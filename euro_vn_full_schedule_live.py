"""
euro_vn_full_schedule_live.py
================================
BẢN HOÀN CHỈNH – 2 GIỜ TRƯỚC + 24 GIỜ TỚI + LỌC THEO GIẢI + ĐỘI RIÊNG
TÍCH HỢP: SofaScore (chính) + Các nguồn JSON phụ (Wheresthematch, LiveSportsOnTV, Ausport)
Tối ưu ghép kênh M3U với matching thông minh (tên kênh + tên trận + quốc gia)
Bổ sung: FA Cup, League Cup (Carabao Cup) – group "Live FA, League Cup"
Sửa lỗi nhận diện UEFA Europa League (không nhầm thành UEFA Euro) cho tất cả nguồn
Match kênh có xét quốc gia, loại bỏ kênh chứa ###, tăng độ chính xác (tránh nhầm Sky Go với Sky Golf)
Thêm bước validate link (kiểm tra stream còn sống) trước khi ghi M3U
Bổ sung match theo tên trận (khi tên kênh M3U chứa trực tiếp tên trận)
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
from difflib import SequenceMatcher
from typing import List, Dict, Optional

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
    "UEFA Euro",
    "FA Cup",
    "League Cup"
}

# Danh sách đội Premier League dùng chung cho các giải Anh
PREMIER_LEAGUE_TEAMS = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton"
}

# Danh sách đội riêng từng giải (tên chuẩn, viết thường)
ALLOWED_TEAMS_PER_LEAGUE = {
    "Premier League": PREMIER_LEAGUE_TEAMS,
    "Serie A": {"inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"},
    "La Liga": {"barcelona", "real madrid", "atletico madrid"},
    "Bundesliga": {"bayern munich", "borussia dortmund", "bayer leverkusen"},
    "Ligue 1": {"psg", "paris saint-germain", "olympique marseille", "marseille"},
    "FA Cup": PREMIER_LEAGUE_TEAMS,
    "League Cup": PREMIER_LEAGUE_TEAMS
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
    "FA Cup": "Live FA, League Cup",
    "League Cup": "Live FA, League Cup",
    "Tennis": "Live Tennis",
    "FIFA World Cup": "Live Fifa World Cup",
    "International Friendly": "Live International Friendly"
}

# Danh sách các đội tuyển được phép ngoài châu Âu (cho giao hữu)
ALLOWED_NON_EURO_TEAMS = {"argentina", "brazil", "japan", "south korea"}

# ================== HELPER ==================
def is_low_resolution(name: str) -> bool:
    n = name.lower()
    return any(x in n for x in ["sd", "360p", "480p", "576p", "low res", "low quality"])

def normalize(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return " ".join(c for c in s if unicodedata.category(c) != "Mn")

def normalize_team_name(name: str) -> str:
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
    """Chuẩn hóa tên kênh: loại bỏ pattern đặc biệt, ký tự thừa, tiền tố, ký tự mũ chữ"""
    name = name.lower()
    # Loại bỏ tiền tố dạng "FI: " (hai chữ cái + dấu hai chấm)
    name = re.sub(r'^[a-z]{2,3}: ', '', name)
    # Loại bỏ tiền tố dạng "UK - " (hai chữ cái + dấu cách + gạch ngang + cách)
    name = re.sub(r'^[a-z]{2,3} - ', '', name)
    # Loại bỏ từ SUOMI và các từ tương tự (có thể là tên nước)
    name = re.sub(r'\b(suomi|dansk|svenska|norsk|suomi|nederlands|deutsch|italia|españa|français|polska|magyar|românia|българия|türkiye|ελλάδα|ישראל)\b', '', name)
    # Loại bỏ ký tự mũ chữ (ᴴᴰ, ⱽᴵᴾ, ᴹᴬˣ, ...)
    name = re.sub(r'[ᴬᴭᴮᴰᴱᴲᴳᴴᴵᴶᴷᴸᴹᴺᴻᴼᴾᴿᵀᵁⱽᵂᵡᵞᵟᵠᵡᵢᵣᵤᵥᵦᵧᵨᵩᵪᵫᵬᵭᵮᵯᵰᵱᵲᵳᵴᵵᵶᵷᵸᵹᵺᵻᵼᵽᵾᵿ]', '', name)
    # Loại bỏ ┃anything┃
    name = re.sub(r'┃[^┃]*┃', '', name)
    # Loại bỏ tiền tố dạng NL|, UK|, USA|
    name = re.sub(r'^[a-z]{2,3}\|', '', name)
    # Loại bỏ ký tự mũ số
    name = re.sub(r'[²³⁴⁵⁶⁷⁸⁹]', '', name)
    # Loại bỏ PPV, HEVC
    name = re.sub(r'\b(ppv|hevc)\b', '', name)
    # Loại bỏ các từ phổ biến
    name = re.sub(r'\b(hd|uhd|4k|fhd|vip|plus|extra|tv|channel|network|sports?|premium|maximo?|4mbps|4g|mbps|kbps|bitrate|stream|live|online)\b', '', name)
    # Loại bỏ cờ
    name = re.sub(r'[🇬🇧🇺🇸🇨🇦🇦🇺🇩🇪🇫🇷🇮🇹🇪🇸🇵🇹🇳🇱🇧🇪🇨🇭🇦🇹🇸🇪🇳🇴🇩🇰🇫🇮🇵🇱🇨🇿🇭🇺🇷🇴🇧🇬🇬🇷🇹🇷]', '', name)
    # Loại bỏ nội dung trong ngoặc
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'\[[^\]]*\]', '', name)
    name = re.sub(r'\{[^}]*\}', '', name)
    # Loại bỏ ký tự đặc biệt, giữ chữ và số
    name = re.sub(r'[^\w\s]', ' ', name)
    # Chuẩn hóa khoảng trắng
    name = ' '.join(name.split())
    # Bỏ dấu
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ascii')
    return name

def split_name_and_number(name: str):
    match = re.search(r'(\d+)$', name)
    if match:
        number = match.group(1)
        text = name[:match.start()].strip()
        return text, number
    return name, None

def normalize_country_name(country: str) -> str:
    if not country:
        return ""
    country_lower = country.lower().strip()
    mapping = {
        # Châu Mỹ
        "united states": "us",
        "united states of america": "us",
        "usa": "us",
        "us": "us",
        "canada": "ca",
        "ca": "ca",
        "brazil": "br",
        "br": "br",
        "argentina": "ar",
        "ar": "ar",
        "chile": "cl",
        "cl": "cl",
        "peru": "pe",
        "colombia": "co",
        "ecuador": "ec",
        "uruguay": "uy",
        "paraguay": "py",
        "bolivia": "bo",
        "venezuela": "ve",
        "mexico": "mx",
        "sur": "sa",  # South America (khu vực)
        # Châu Âu
        "united kingdom": "uk",
        "uk": "uk",
        "great britain": "uk",
        "england": "uk",
        "ireland": "ie",
        "ie": "ie",
        "germany": "de",
        "de": "de",
        "deutschland": "de",
        "france": "fr",
        "fr": "fr",
        "french": "fr",
        "italy": "it",
        "it": "it",
        "italia": "it",
        "spain": "es",
        "es": "es",
        "espana": "es",
        "portugal": "pt",
        "pt": "pt",
        "netherlands": "nl",
        "nl": "nl",
        "nederland": "nl",
        "belgium": "be",
        "be": "be",
        "austria": "at",
        "at": "at",
        "switzerland": "ch",
        "ch": "ch",
        "croatia": "hr",
        "hr": "hr",
        "hrvatska": "hr",
        "serbia": "rs",
        "rs": "rs",
        "srbija": "rs",
        "turkey": "tr",
        "tr": "tr",
        "türkiye": "tr",
        "poland": "pl",
        "pl": "pl",
        "polska": "pl",
        "czech republic": "cz",
        "cz": "cz",
        "czech": "cz",
        "slovakia": "sk",
        "slovenia": "si",
        "hungary": "hu",
        "hu": "hu",
        "romania": "ro",
        "ro": "ro",
        "bulgaria": "bg",
        "greece": "gr",
        "gr": "gr",
        "hellas": "gr",
        "denmark": "dk",
        "dk": "dk",
        "danmark": "dk",
        "sweden": "se",
        "se": "se",
        "sverige": "se",
        "norway": "no",
        "no": "no",
        "norge": "no",
        "finland": "fi",
        "fi": "fi",
        "suomi": "fi",
        "estonia": "ee",
        "latvia": "lv",
        "lithuania": "lt",
        "iceland": "is",
        "albania": "al",
        "al": "al",
        "north macedonia": "mk",
        "montenegro": "me",
        "bosnia and herzegovina": "ba",
        "luxembourg": "lu",
        "malta": "mt",
        "cyprus": "cy",
        "baltics": "balt",  # gộp, nhưng thực tế mỗi nước có mã riêng
        # Châu Á - Thái Bình Dương
        "australia": "au",
        "au": "au",
        "japan": "jp",
        "south korea": "kr",
        "india": "in",
        "indonesia": "id",
        "malaysia": "my",
        "singapore": "sg",
        "china": "cn",
        "vietnam": "vn",
        "thailand": "th",
        # Trung Đông
        "israel": "il",
        "saudi arabia": "sa",
        "uae": "ae",
        "qatar": "qa",
        # Mã 2 chữ cái (giữ nguyên)
    }
    if country_lower in mapping:
        return mapping[country_lower]
    if len(country_lower) == 2:
        return country_lower
    try:
        c = pycountry.countries.get(name=country)
        if c:
            return c.alpha_2.lower()
    except:
        pass
    return country_lower

def extract_match_from_m3u_name(m3u_name: str) -> str:
    # Loại bỏ các tiền tố phổ biến
    cleaned = re.sub(r'^(NEXT\s*\|\s*|EN ESPAÑOL-|AO VIVO:\s*|UK\s*-\s*|[A-Z]{2,3}\s*\([^)]+\)\s*\|\s*|[A-Z]{2,3}:\s*)', '', m3u_name, flags=re.IGNORECASE)
    # Loại bỏ thông tin ngày giờ
    cleaned = re.sub(r'\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{2,4}\s+\d{2}:\d{2}\s+[A-Z]{3,4}\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}', '', cleaned)
    cleaned = re.sub(r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}', '', cleaned, flags=re.IGNORECASE)
    # Loại bỏ tên giải đấu
    cleaned = re.sub(r'\b(LA\s+LIGA|LALIGA|EA\s+SPORTS|PREMIER\s+LEAGUE|UEFA|CHAMPIONS\s+LEAGUE|EUROPA\s+LEAGUE|CONFERENCE\s+LEAGUE)\b', '', cleaned, flags=re.IGNORECASE)
    # Loại bỏ các từ thừa
    cleaned = re.sub(r'\b(8K\s+EXCLUSIVE|PPV|HD|FHD|UHD|LIVE|EXCLUSIVE)\b', '', cleaned, flags=re.IGNORECASE)
    # Chuẩn hóa dấu phân cách thành " vs "
    cleaned = re.sub(r'[-–—]', ' vs ', cleaned)
    cleaned = re.sub(r'\bVS\.?\b', ' vs ', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bx\b', ' vs ', cleaned, flags=re.IGNORECASE)
    # Loại bỏ ký tự đặc biệt
    cleaned = re.sub(r'[^\w\s]', ' ', cleaned)
    cleaned = ' '.join(cleaned.split())
    return cleaned.lower().strip()

def is_channel_match(ch_name: str, m3u_name: str, country: str = "") -> bool:
    if not ch_name or not m3u_name:
        return False
    
    if re.search(r'#{3,}', m3u_name):
        return False
    
    ch_norm = normalize_channel_name(ch_name)
    m3u_norm = normalize_channel_name(m3u_name)
    
    if country:
        country_code = normalize_country_name(country)
        if country_code:
            m3u_lower = m3u_name.lower()
            match = re.search(r'(?:\||^|\(|\s)([a-z]{2,3})(?:\||:|\)|\s|-|$)', m3u_lower)
            if match:
                prefix = match.group(1)
                if prefix != country_code:
                    return False
    
    if len(ch_norm) <= 3 or len(m3u_norm) <= 3:
        return ch_norm == m3u_norm
    
    ch_text, ch_num = split_name_and_number(ch_norm)
    m3u_text, m3u_num = split_name_and_number(m3u_norm)
    
    text_similarity = similar(ch_text, m3u_text)
    if text_similarity < 0.9:
        return False
    if abs(len(ch_text) - len(m3u_text)) > max(len(ch_text), len(m3u_text)) * 0.3:
        return False
    
    if ch_num is not None and m3u_num is not None:
        return ch_num == m3u_num
    if ch_num is not None or m3u_num is not None:
        return False
    
    # Tránh nhầm "go" với "golf"
    ch_lower = ch_name.lower()
    m3u_lower = m3u_name.lower()
    if "go" in ch_lower and "golf" in m3u_lower and "go" not in m3u_lower:
        if similar("go", "golf") < 0.5:
            return False
    
    return True

def is_team_match(team_name: str, m3u_name: str) -> bool:
    team_norm = normalize(team_name)
    # Trích xuất tên trận từ m3u_name (nếu có)
    extracted = extract_match_from_m3u_name(m3u_name)
    if extracted:
        m3u_norm = normalize(extracted)
    else:
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
    if "europa league" in name_lower:
        return False
    if any(x in name_lower for x in ["u19", "u21", "u17", "youth"]):
        return False
    euro_keywords = ["euro", "uefa european championship", "european championship"]
    return any(kw in name_lower for kw in euro_keywords)

def is_uefa_champions(tournament_name: str) -> bool:
    return "uefa champions league" in tournament_name.lower()

def is_friendly_match(home_team: str, away_team: str) -> bool:
    home_norm = normalize(home_team)
    away_norm = normalize(away_team)
    home_country = away_country = None
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

async def fetch_sofascore_event(session, event_id, sport, start_ts, max_ts):
    url = f"https://api.sofascore.com/api/v1/event/{event_id}"
    try:
        res = await session.get(url, impersonate="chrome120", timeout=10)
        if res.status_code != 200: return None
        ev = res.json().get('event', {})
        start_ts_ev = ev.get('startTimestamp')
        if not start_ts_ev or not (start_ts <= start_ts_ev <= max_ts):
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
                "time": vn_time(start_ts_ev),
                "match": match,
                "kick_utc": start_ts_ev,
                "tv_channels": tv,
                "tournament": ev.get('tournament', {}).get('name')
            }
        else:
            league_raw = ev.get('tournament', {}).get('name', 'Unknown')
            league_lower = league_raw.lower()
            home_team = ev.get('homeTeam', {}).get('name', '')
            away_team = ev.get('awayTeam', {}).get('name', '')

            if any(x in league_lower for x in ["women", "frauen", "u19", "u21", "u17", "youth"]):
                return None

            if "uefa europa league" in league_lower:
                league = "UEFA Europa League"
            elif "uefa conference league" in league_lower:
                league = "UEFA Europa Conference League"
            elif is_uefa_champions(league_raw):
                league = "UEFA Champions League"
            elif is_uefa_euro(league_raw):
                league = "UEFA Euro"
            elif "fa cup" in league_lower:
                league = "FA Cup"
            elif "carabao cup" in league_lower or "league cup" in league_lower:
                league = "League Cup"
            elif "premier league" in league_lower:
                league = "Premier League"
            elif "serie a" in league_lower:
                league = "Serie A"
            elif "bundesliga" in league_lower:
                league = "Bundesliga"
            elif "la liga" in league_lower or "laliga" in league_lower:
                league = "La Liga"
            elif "ligue 1" in league_lower:
                league = "Ligue 1"
            elif "world cup" in league_lower or "fifa world cup" in league_lower:
                league = "FIFA World Cup"
            elif "friendly" in league_lower or "international friendly" in league_lower:
                league = "International Friendly"
            else:
                return None

            if league in ALLOWED_TEAMS_PER_LEAGUE:
                allowed = ALLOWED_TEAMS_PER_LEAGUE[league]
                home_norm = normalize_team_name(home_team)
                away_norm = normalize_team_name(away_team)
                if not (home_norm in allowed or away_norm in allowed):
                    return None

            if league not in ALLOWED_FOOTBALL_LEAGUES and league not in ["FIFA World Cup", "International Friendly"]:
                return None

            match = f"{home_team} vs {away_team}"
            return {
                "league": league,
                "time": vn_time(start_ts_ev),
                "match": match,
                "kick_utc": start_ts_ev,
                "tv_channels": tv,
                "tournament": league_raw
            }
    except:
        return None

async def scrape_sofascore(start_ts: int, max_ts: int) -> List[Dict]:
    all_games = []
    async with AsyncSession() as session:
        for sport in ["football", "tennis"]:
            now = datetime.now()
            dates = [now.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")]
            for date_str in dates:
                url = f"https://www.sofascore.com/api/v1/sport/{sport}/scheduled-events/{date_str}"
                res = await session.get(url, impersonate="chrome120", timeout=30)
                if res.status_code != 200: continue
                events = res.json().get('events', [])
                tasks = [fetch_sofascore_event(session, e['id'], sport, start_ts, max_ts) for e in events]
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
        if "Tennis" in league:
            league = "Tennis"
        else:
            if "UEFA Europa League" in league:
                league = "UEFA Europa League"
            elif "UEFA Europa Conference League" in league:
                league = "UEFA Europa Conference League"
            elif "Premier League" in league:
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
            elif "FA Cup" in league:
                league = "FA Cup"
            elif "League Cup" in league or "Carabao" in league:
                league = "League Cup"
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
    except:
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
        if sport == "Tennis" or "Tennis" in league:
            league = "Tennis"
        else:
            if "UEFA Europa League" in league:
                league = "UEFA Europa League"
            elif "UEFA Europa Conference League" in league:
                league = "UEFA Europa Conference League"
            elif "Premier League" in league:
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
            elif "FA Cup" in league:
                league = "FA Cup"
            elif "League Cup" in league or "Carabao" in league:
                league = "League Cup"
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
    except:
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
        if "Europa League" in league:
            league = "UEFA Europa League"
        elif "Europa Conference League" in league:
            league = "UEFA Europa Conference League"
        elif "Premier League" in league:
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
        elif "FA Cup" in league:
            league = "FA Cup"
        elif "League Cup" in league or "Carabao" in league:
            league = "League Cup"
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

# ================== LIVEONSAT ==================

def load_liveonsat_data() -> List[Dict]:
    """Tải dữ liệu từ liveonsat_raw.json, không lọc thời gian (chỉ để bổ sung kênh)"""
    url = "https://raw.githubusercontent.com/a7shk1/liveonsat/refs/heads/main/matches/liveonsat_raw.json"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"   Lỗi tải liveonsat: {e}")
        return []

    games = []
    date_str = data.get("date")
    if not date_str:
        return games

    for match in data.get("matches", []):
        title = match.get("title", "").strip()
        kickoff_str = match.get("kickoff_baghdad")
        channels_raw = match.get("channels_raw", [])

        if not title or not kickoff_str:
            continue

        # Chuyển đổi thời gian (giữ lại để dùng cho việc merge, nhưng không lọc)
        try:
            dt_str = f"{date_str} {kickoff_str}"
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            dt = dt.replace(tzinfo=ZoneInfo("Asia/Baghdad"))
            kick_utc = int(dt.timestamp())
        except:
            continue

        # Chuẩn hóa tên trận
        title_norm = title.replace(" v ", " vs ").replace(" V ", " vs ")

        # Lọc kênh rác
        clean_channels = []
        for ch in channels_raw:
            ch_clean = ch.strip()
            if not ch_clean:
                continue
            if any(x in ch_clean.lower() for x in [
                "discover more", "tv schedule", "app", "gear", "merchandise",
                "flag", "betting", "custom", "fitness", "tracker", "scarf",
                "cookie", "privacy", "rights reserved", "liveonsat.com"
            ]):
                continue
            if len(ch_clean) < 3:
                continue
            clean_channels.append(ch_clean)

        if not clean_channels:
            continue

        # Xác định league dựa trên tên đội trong title (chuẩn hóa)
        league = None
        # Tách tên đội từ title (loại bỏ "vs")
        parts = title_norm.split(" vs ")
        if len(parts) == 2:
            home_norm = normalize_team_name(parts[0])
            away_norm = normalize_team_name(parts[1])
            # Kiểm tra Premier League
            if home_norm in PREMIER_LEAGUE_TEAMS or away_norm in PREMIER_LEAGUE_TEAMS:
                league = "Premier League"
            # Serie A
            elif home_norm in ALLOWED_TEAMS_PER_LEAGUE["Serie A"] or away_norm in ALLOWED_TEAMS_PER_LEAGUE["Serie A"]:
                league = "Serie A"
            # La Liga
            elif home_norm in ALLOWED_TEAMS_PER_LEAGUE["La Liga"] or away_norm in ALLOWED_TEAMS_PER_LEAGUE["La Liga"]:
                league = "La Liga"
            # Bundesliga
            elif home_norm in ALLOWED_TEAMS_PER_LEAGUE["Bundesliga"] or away_norm in ALLOWED_TEAMS_PER_LEAGUE["Bundesliga"]:
                league = "Bundesliga"
            # Ligue 1
            elif home_norm in ALLOWED_TEAMS_PER_LEAGUE["Ligue 1"] or away_norm in ALLOWED_TEAMS_PER_LEAGUE["Ligue 1"]:
                league = "Ligue 1"

        # Nếu không xác định được, bỏ qua (không thêm vào danh sách)
        if league is None:
            continue

        games.append({
            "league": league,
            "match": title_norm,
            "kick_utc": kick_utc,
            "time": vn_time(kick_utc),
            "tv_channels": [{"country": "LiveOnSat", "channels": clean_channels}],
            "source": "liveonsat"
        })
    print(f"   liveonsat: đã xử lý {len(games)} trận (không lọc thời gian)")
    return games

def load_all_secondary_sources(start_ts: int, max_ts: int) -> List[Dict]:
    games = []
    for func, fname in [(parse_livesportsontv, "schedule_livesportsontv.json"),
                        (parse_wheresthematch, "results.json"),
                        (parse_ausport, "ausport_schedule.json")]:
        data = load_json_file(fname)
        for entry in data:
            g = func(entry)
            if g and start_ts <= g['kick_utc'] <= max_ts:
                games.append(g)

    # Thêm liveonsat (không lọc thời gian)
    liveonsat_games = load_liveonsat_data()
    games.extend(liveonsat_games)
    return games

# ================== MERGE ==================
def merge_games(primary: List[Dict], secondary: List[Dict]) -> List[Dict]:
    primary_football = [g for g in primary if g['league'] != "Tennis"]
    primary_tennis = [g for g in primary if g['league'] == "Tennis"]
    secondary_football = [g for g in secondary if g['league'] != "Tennis"]
    secondary_tennis = [g for g in secondary if g['league'] == "Tennis"]

    # Tạo index cho primary_football
    primary_index = [(game, normalize(game['match']), game['kick_utc'], game['league']) for game in primary_football]

    for sec in secondary_football:
        sec_norm_match = normalize(sec['match'])
        sec_ts = sec['kick_utc']
        sec_league = sec['league']

        best_match = None
        best_score = 0.0
        for game, norm_match, ts, league in primary_index:
            if league != sec_league:
                continue
            if abs(ts - sec_ts) > 3600:  # chênh lệch tối đa 1 giờ
                continue
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
        # else: không thêm trận mới từ secondary (bỏ qua)

    # Xử lý tennis: gộp theo thời gian
    all_tennis = primary_tennis + secondary_tennis
    seen = {}
    unique_tennis = []
    for g in all_tennis:
        key = (g['kick_utc'], g.get('match', ''))
        if key not in seen:
            seen[key] = g
            unique_tennis.append(g)
        else:
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
            current['name'] = name_part[1].strip() if len(name_part)>1 else "Unknown"
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
# ================== Trích xuất headers từ extra ==================
def extract_headers_from_extra(extra_lines):
    headers = {}
    if not extra_lines:
        return headers
    for line in extra_lines:
        line = line.strip()
        if line.startswith('#EXTVLCOPT'):
            # Định dạng: #EXTVLCOPT:http-user-agent=...
            # hoặc #EXTVLCOPT:http-cookie=...
            # hoặc #EXTVLCOPT:http-header=Authorization: Bearer ...
            parts = line.split(':', 2)
            if len(parts) >= 3:
                opt_type = parts[1].strip()
                value = parts[2].strip()
                if opt_type == 'http-user-agent':
                    headers['User-Agent'] = value
                elif opt_type == 'http-cookie':
                    headers['Cookie'] = value
                elif opt_type == 'http-header':
                    if ': ' in value:
                        header_name, header_value = value.split(': ', 1)
                        headers[header_name] = header_value
    return headers
# ================== VALIDATE STREAM ==================
async def validate_stream_url(session, url: str, extra_headers: dict = None) -> bool:
    try:
        default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if extra_headers:
            default_headers.update(extra_headers)
        
        # Thử HEAD trước
        resp = await session.head(url, headers=default_headers, timeout=5, allow_redirects=True)
        if resp.status_code in [200, 202, 204, 206]:
            return True
        
        # Nếu HEAD thất bại, thử GET với range nhỏ
        range_headers = {"Range": "bytes=0-1024", **default_headers}
        resp2 = await session.get(url, headers=range_headers, timeout=5)
        if resp2.status_code in [200, 206, 202]:
            text = await resp2.text()
            if "<html" in text.lower() or "access denied" in text.lower() or "401" in text:
                return False
            return True
        return False
    except Exception:
        return False
# ================== MAIN ==================
async def main():
    start = time.time()
    vn_now = datetime.now(TIMEZONE)
    start_ts = int(datetime.now(TIMEZONE).timestamp()) - 7200   # 2 giờ trước
    max_ts = int(datetime.now(TIMEZONE).timestamp()) + 86400    # 24 giờ sau

    print("🔄 Bắt đầu lấy lịch từ 2 GIỜ TRƯỚC đến 24 GIỜ TỚI từ SofaScore và các nguồn JSON phụ...")

    print("📡 Đang lấy dữ liệu từ SofaScore...")
    sofascore_games = await scrape_sofascore(start_ts, max_ts)
    print(f"   ✅ SofaScore: {len(sofascore_games)} trận")

    print("📡 Đang đọc các nguồn JSON phụ...")
    secondary_games = load_all_secondary_sources(start_ts, max_ts)
    print(f"   ✅ Các nguồn phụ: {len(secondary_games)} trận")

    print("🔄 Đang merge dữ liệu...")
    all_games = merge_games(sofascore_games, secondary_games)

    # Lọc trùng (không lọc theo thời gian vì đã lọc từ đầu)
    seen = {}
    deduped = []
    for g in all_games:
        if g['league'] == "Tennis" and not g['match']:
            key = (g['kick_utc'], g['league'])
        else:
            key = normalize(g["match"]) + "|" + g["time"] if g["match"] else g["time"] + "|" + str(g["kick_utc"])
        if key not in seen:
            seen[key] = g
            deduped.append(g)
        else:
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

    # ================== XỬ LÝ M3U ==================
    print("📥 Đang tải và phân tích M3U...")
    m3u_links = []
    try:
        with open(M3U_LIST_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and line.startswith('http'):
                    m3u_links.append(line)
        print(f"   📋 Tìm thấy {len(m3u_links)} URL trong M3U_list.txt")
    except Exception as e:
        print(f"   ❌ Lỗi đọc file M3U_list.txt: {e}")
        m3u_links = []

    def fetch_text_sync(url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"   Lỗi tải {url[:50]}...: {e}")
            return None

    all_ch = []
    if m3u_links:
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(fetch_text_sync, url): url for url in m3u_links}
            for fut in as_completed(futures):
                content = fut.result()
                if content:
                    chs = parse_m3u(content)
                    for ch in chs:
                        if re.search(r'#{3,}', ch.get('name', '')):
                            continue
                        if is_low_resolution(ch.get('name', '')):
                            continue
                        all_ch.append(ch)
    else:
        print("   ⚠️ Không có link M3U nào để tải.")

    unique_ch = list({ch['url']: ch for ch in all_ch if ch.get('url')}.values())
    print(f"   ✅ Đã tải {len(unique_ch)} kênh")

    print("🔄 Đang match kênh với lịch...")
    live_events = []
    for g in all_games:
        try:
            used_urls_in_match = set()
            for tv in g.get("tv_channels", []):
                tv_country = tv.get("country", "")
                for ch_name in tv.get("channels", []):
                    matching = [ch for ch in unique_ch if is_channel_match(ch_name, ch['name'], tv_country)]
                    for ch in matching:
                        url = ch['url']
                        if url in used_urls_in_match:
                            continue
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
                for ch in unique_ch:
                    if is_team_match(match_norm, ch['name']):
                        url = ch['url']
                        if url in used_urls_in_match:
                            continue
                        used_urls_in_match.add(url)
                        display_name = f"{g['time']} | {g['match']} (M3U: {ch['name']})"
                        live_events.append({
                            "datetime": datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE),
                            "name": display_name,
                            "channel": ch,
                            "league": g["league"]
                        })
                        break
        except Exception as e:
            print(f"   Lỗi xử lý trận {g.get('match', '')}: {e}")
            continue

    # ================== VALIDATE STREAMS ==================
    print("🔍 Đang kiểm tra tính sống của các link (HEAD request với headers đầy đủ, timeout 5s)...")
    async with AsyncSession() as session:
        tasks = []
        for ev in live_events:
            extra_headers = extract_headers_from_extra(ev['channel'].get('extra', []))
            tasks.append(validate_stream_url(session, ev['channel']['url'], extra_headers))
        results = await asyncio.gather(*tasks)
    validated_events = [ev for ev, is_alive in zip(live_events, results) if is_alive]
    print(f"   ✅ {len(validated_events)}/{len(live_events)} kênh hoạt động")
    live_events = validated_events

    # Xử lý tennis: nhóm kênh trùng
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
    print(f"   • live_schedule.m3u: {len(live_events)} kênh (matching thông minh + validate)")

if __name__ == "__main__":
    asyncio.run(main())
