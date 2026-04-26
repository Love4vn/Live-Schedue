"""
euro_vn_full_schedule_live.py
================================
PHIÊN BẢN DÙNG PLAYWRIGHT ĐỂ LẤY SOFASCORE (KHẮC PHỤC 403)
"""

import asyncio
import json
import re
import unicodedata
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from difflib import SequenceMatcher
from typing import List, Dict, Optional
from itertools import groupby

import pycountry
import aiohttp
from curl_cffi.requests import AsyncSession as CffiAsyncSession

# ================== CẤU HÌNH ==================
ENABLE_VALIDATION = False
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
M3U_LIST_FILE = "M3U_list.txt"
SCHEDULE_FILE = "schedule.json"
LIVE_M3U = "live_schedule.m3u"
SOFASCORE_CACHE_FILE = "sofascore_cache.json"
VALIDATE_TIMEOUT = 2
MAX_CHANNELS_PER_MATCH = 500
HEAD_CONCURRENCY = 100
DEBUG_MATCH = True
DEBUG_MERGE = True
DEBUG_SOFASCORE = True

ALLOWED_TENNIS_TOURNAMENTS = {
    "atp", "atp tour", "atp world tour", "grand slam", "australian open",
    "roland garros", "french open", "wimbledon", "us open", "nitto atp finals",
    "atp masters", "atp 1000", "atp 500", "atp 250"
}

ALLOWED_FOOTBALL_LEAGUES = {
    "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "UEFA Euro", "FA Cup", "League Cup"
}

PREMIER_LEAGUE_TEAMS = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton"
}

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
    "Premier League": "⚽️🏴󠁧󠁢󠁥󠁮󠁧󠁿|Live Premier League",
    "Serie A": "⚽️🇮🇹|Live Serie A",
    "Bundesliga": "⚽️🇩🇪|Live Bundesliga",
    "La Liga": "⚽️🇪🇦|Live La Liga",
    "Ligue 1": "⚽️🇨🇵|Live Ligue 1",
    "UEFA Champions League": "Live UEFA Champions League",
    "UEFA Europa League": "Live UEFA Europa League",
    "UEFA Europa Conference League": "Live UEFA Conference League",
    "UEFA Euro": "Live Euro",
    "FA Cup": "Live FA, League Cup",
    "League Cup": "Live FA, League Cup",
    "Tennis": "🎾|Live Tennis",
    "FIFA World Cup": "Live Fifa World Cup",
    "International Friendly": "Live International Friendly"
}

ALLOWED_NON_EURO_TEAMS = {"argentina", "brazil", "japan", "south korea"}

# ================== HELPER FUNCTIONS ==================
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
    name = name.lower()
    name = re.sub(r'^[a-z]{2,3}: ', '', name)
    name = re.sub(r'^[a-z]{2,3} - ', '', name)
    name = re.sub(r'\b(suomi|dansk|svenska|norsk|nederlands|deutsch|italia|españa|français|polska|magyar|românia|българия|türkiye|ελλάδα|ישראל|hrvatska|croatia)\b', '', name)
    name = re.sub(r'[ᴬᴭᴮᴰᴱᴲᴳᴴᴵᴶᴷᴸᴹᴺᴻᴼᴾᴿᵀᵁⱽᵂᵡᵞᵟᵠᵡᵢᵣᵤᵥᵦᵧᵨᵩᵪᵫᵬᵭᵮᵯᵰᵱᵲᵳᵴᵵᵶᵷᵸᵹᵺᵻᵼᵽᵾᵿ]', '', name)
    name = re.sub(r'┃[^┃]*┃', '', name)
    name = re.sub(r'^[a-z]{2,3}\|', '', name)
    name = re.sub(r'[²³⁴⁵⁶⁷⁸⁹]', '', name)
    name = re.sub(r'\b(ppv|hevc)\b', '', name)
    name = re.sub(r'\b(hd|uhd|4k|fhd|vip|plus|extra|tv|channel|network|sports?|premium|maximo?|4mbps|4g|mbps|kbps|bitrate|stream|live|online)\b', '', name)
    name = re.sub(r'[🇬🇧🇺🇸🇨🇦🇦🇺🇩🇪🇫🇷🇮🇹🇪🇸🇵🇹🇳🇱🇧🇪🇨🇭🇦🇹🇸🇪🇳🇴🇩🇰🇫🇮🇵🇱🇨🇿🇭🇺🇷🇴🇧🇬🇬🇷🇹🇷]', '', name)
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'\[[^\]]*\]', '', name)
    name = re.sub(r'\{[^}]*\}', '', name)
    name = re.sub(r'[^\w\s]', ' ', name)
    name = ' '.join(name.split())
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
        "united states": "us", "usa": "us", "us": "us", "canada": "ca", "ca": "ca",
        "brazil": "br", "br": "br", "argentina": "ar", "ar": "ar", "chile": "cl",
        "cl": "cl", "peru": "pe", "colombia": "co", "ecuador": "ec", "uruguay": "uy",
        "paraguay": "py", "bolivia": "bo", "venezuela": "ve", "mexico": "mx",
        "united kingdom": "uk", "uk": "uk", "england": "uk", "ireland": "ie", "ie": "ie",
        "germany": "de", "de": "de", "france": "fr", "fr": "fr", "italy": "it", "it": "it",
        "spain": "es", "es": "es", "portugal": "pt", "pt": "pt", "netherlands": "nl",
        "nl": "nl", "belgium": "be", "be": "be", "austria": "at", "at": "at",
        "switzerland": "ch", "ch": "ch", "croatia": "hr", "hr": "hr", "serbia": "rs",
        "rs": "rs", "turkey": "tr", "tr": "tr", "poland": "pl", "pl": "pl",
        "czech republic": "cz", "cz": "cz", "slovakia": "sk", "slovenia": "si",
        "hungary": "hu", "hu": "hu", "romania": "ro", "ro": "ro", "bulgaria": "bg",
        "greece": "gr", "gr": "gr", "denmark": "dk", "dk": "dk", "sweden": "se",
        "se": "se", "norway": "no", "no": "no", "finland": "fi", "fi": "fi",
        "australia": "au", "au": "au", "japan": "jp", "south korea": "kr", "india": "in",
        "indonesia": "id", "malaysia": "my", "singapore": "sg", "china": "cn",
        "vietnam": "vn", "thailand": "th", "israel": "il", "saudi arabia": "sa",
        "uae": "ae", "qatar": "qa"
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
    cleaned = re.sub(r'^(NEXT\s*\|\s*|EN ESPAÑOL-|AO VIVO:\s*|UK\s*-\s*|[A-Z]{2,3}\s*\([^)]+\)\s*\|\s*|[A-Z]{2,3}:\s*)', '', m3u_name, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{2,4}\s+\d{2}:\d{2}\s+[A-Z]{3,4}\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}', '', cleaned)
    cleaned = re.sub(r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b(LA\s+LIGA|LALIGA|EA\s+SPORTS|PREMIER\s+LEAGUE|UEFA|CHAMPIONS\s+LEAGUE|EUROPA\s+LEAGUE|CONFERENCE\s+LEAGUE)\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b(8K\s+EXCLUSIVE|PPV|HD|FHD|UHD|LIVE|EXCLUSIVE)\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'[-–—]', ' vs ', cleaned)
    cleaned = re.sub(r'\bVS\.?\b', ' vs ', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bx\b', ' vs ', cleaned, flags=re.IGNORECASE)
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
    if len(ch_norm) <= 3 or len(m3u_norm) <= 3:
        return ch_norm == m3u_norm
    ch_text, ch_num = split_name_and_number(ch_norm)
    m3u_text, m3u_num = split_name_and_number(m3u_norm)
    text_similarity = similar(ch_text, m3u_text)
    if text_similarity < 0.8:
        return False
    if abs(len(ch_text) - len(m3u_text)) > max(len(ch_text), len(m3u_text)) * 0.3:
        return False
    if ch_num is not None and m3u_num is not None:
        return ch_num == m3u_num
    if ch_num is not None or m3u_num is not None:
        return False
    ch_lower = ch_name.lower()
    m3u_lower = m3u_name.lower()
    if "go" in ch_lower and "golf" in m3u_lower and "go" not in m3u_lower:
        if similar("go", "golf") < 0.5:
            return False
    return True

def is_team_match(team_name: str, m3u_name: str) -> bool:
    team_norm = normalize(team_name)
    extracted = extract_match_from_m3u_name(m3u_name)
    if extracted:
        m3u_norm = normalize(extracted)
    else:
        m3u_norm = normalize_channel_name(m3u_name)
    return similar(team_norm, m3u_norm) >= 0.7

def get_country_priority(country_name: str) -> int:
    if not country_name:
        return 100
    priority_map = {
        "united kingdom": 1, "uk": 1, "england": 1,
        "united states": 2, "usa": 2,
        "australia": 3, "canada": 4, "ireland": 5,
        "new zealand": 6, "south africa": 7,
    }
    country_lower = country_name.lower()
    for key, prio in priority_map.items():
        if key in country_lower:
            return prio
    return 50

def normalize_sofascore_league(league_raw: str) -> Optional[str]:
    name = league_raw.lower().strip()
    if "uefa europa league" in name: return "UEFA Europa League"
    if "uefa conference league" in name: return "UEFA Europa Conference League"
    if "uefa champions league" in name: return "UEFA Champions League"
    if is_uefa_euro(league_raw): return "UEFA Euro"
    if "fa cup" in name: return "FA Cup"
    if "carabao cup" in name or "league cup" in name: return "League Cup"
    if "premier league" in name: return "Premier League"
    if "serie a" in name: return "Serie A"
    if "la liga" in name or "laliga" in name: return "La Liga"
    if "bundesliga" in name: return "Bundesliga"
    if "ligue 1" in name: return "Ligue 1"
    if "world cup" in name or "fifa world cup" in name: return "FIFA World Cup"
    if "friendly" in name or "international friendly" in name: return "International Friendly"
    return None

def is_uefa_euro(tournament_name: str) -> bool:
    name_lower = tournament_name.lower()
    if "europa league" in name_lower: return False
    if any(x in name_lower for x in ["u19", "u21", "u17", "youth"]): return False
    euro_keywords = ["euro", "uefa european championship", "european championship"]
    return any(kw in name_lower for kw in euro_keywords)

def is_uefa_champions(tournament_name: str) -> bool:
    return "uefa champions league" in tournament_name.lower()

# ================== SOFASCORE SCRAPER (PLAYWRIGHT) ==================
async def scrape_sofascore(start_ts: int, max_ts: int) -> List[Dict]:
    """
    Dùng Playwright để mở schedule page và bắt scheduled-events API response.
    Return list game dictionaries như cũ.
    """
    all_games = []
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("❌ Playwright chưa cài đặt. Dùng phương thức curl_cffi (có thể thất bại 403).")
        # fallback to old curl_cffi
        return await _scrape_sofascore_curl(start_ts, max_ts)

    STEALTH_SCRIPT = """
    Object.defineProperty(navigator, "webdriver", {get: () => undefined});
    window.chrome = {runtime: {}};
    Object.defineProperty(navigator, "plugins", {get: () => [1, 2, 3, 4, 5]});
    Object.defineProperty(navigator, "languages", {get: () => ["en-US", "en"]});
    """
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        await context.add_init_script(STEALTH_SCRIPT)
        page = await context.new_page()

        for sport in ["football", "tennis"]:
            now = datetime.now()
            dates = [now.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")]
            for date_str in dates:
                print(f"   [SofaScore] Mở page {sport} {date_str} bằng Playwright...")
                # Bắt request
                captured_events = []
                pending = {}
                lock = asyncio.Lock()

                cdp = await page.context.new_cdp_session(page)
                async def on_request(params):
                    url = params.get("request", {}).get("url", "")
                    rid = params.get("requestId", "")
                    if f"scheduled-events/{date_str}" in url:
                        async with lock:
                            pending[rid] = url

                async def on_loading_finished(params):
                    rid = params.get("requestId", "")
                    async with lock:
                        url = pending.pop(rid, None)
                    if url is None:
                        return
                    try:
                        resp = await cdp.send("Network.getResponseBody", {"requestId": rid})
                        raw = resp.get("body", "")
                        if resp.get("base64Encoded"):
                            raw = base64.b64decode(raw).decode("utf-8", errors="replace")
                        data = json.loads(raw)
                        events = data.get("events", [])
                        async with lock:
                            captured_events.extend(events)
                        print(f"   [SofaScore] Đã bắt {len(events)} sự kiện từ {url}")
                    except Exception as e:
                        print(f"   [SofaScore] Lỗi đọc body: {e}")

                cdp.on("Network.requestWillBeSent", on_request)
                cdp.on("Network.loadingFinished", on_loading_finished)
                await cdp.send("Network.enable", {})

                try:
                    await page.goto(f"https://www.sofascore.com/{sport}/{date_str}", wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(5000)
                except Exception as e:
                    print(f"   [SofaScore] Lỗi tải trang: {e}")
                finally:
                    await cdp.detach()

                # Xử lý captured_events thành game dict
                for event in captured_events:
                    game = await _parse_sofascore_event_from_raw(event, sport, start_ts, max_ts)
                    if game:
                        all_games.append(game)
                await asyncio.sleep(2)

        await browser.close()
    return all_games

async def _parse_sofascore_event_from_raw(event: dict, sport: str, start_ts: int, max_ts: int) -> Optional[Dict]:
    """Parse event từ raw dict giống như fetch_sofascore_event cũ."""
    try:
        start_ts_ev = event.get('startTimestamp')
        if not start_ts_ev or not (start_ts <= start_ts_ev <= max_ts):
            return None
        # TV data không có trong scheduled-events, cần gọi thêm API (có thể bỏ qua hoặc dùng async lấy)
        # Ở đây ta sẽ không lấy TV data vì Playwright đã dùng để lấy events, giữ nguyên cấu trúc game không có tv_channels.
        # Để lấy kênh, cần gọi API khác (có thể dùng curl_cffi riêng). Tạm thời trả về game với tv_channels rỗng.
        if sport == "tennis":
            tournament = event.get('tournament', {}).get('name', '').lower()
            if not any(keyword in tournament for keyword in ALLOWED_TENNIS_TOURNAMENTS):
                return None
            league = "Tennis"
            match = f"{event.get('homeTeam', {}).get('name', '')} vs {event.get('awayTeam', {}).get('name', '')}"
            return {
                "league": league,
                "time": vn_time(start_ts_ev),
                "match": match,
                "kick_utc": start_ts_ev,
                "tv_channels": [],  # sẽ bổ sung sau nếu cần
                "tournament": event.get('tournament', {}).get('name')
            }
        else:
            league_raw = event.get('tournament', {}).get('name', 'Unknown')
            home_team = event.get('homeTeam', {}).get('name', '')
            away_team = event.get('awayTeam', {}).get('name', '')
            # Filter league
            league = normalize_sofascore_league(league_raw)
            if not league:
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
                "tv_channels": [],  # sẽ bổ sung sau
                "tournament": league_raw
            }
    except:
        return None

# Fallback curl_cffi (giữ nguyên code cũ)
async def _scrape_sofascore_curl(start_ts: int, max_ts: int) -> List[Dict]:
    all_games = []
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.sofascore.com/",
        "Origin": "https://www.sofascore.com",
    }
    async with CffiAsyncSession(headers=headers) as session:
        for sport in ["football", "tennis"]:
            now = datetime.now()
            dates = [now.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")]
            for date_str in dates:
                url = f"https://www.sofascore.com/api/v1/sport/{sport}/scheduled-events/{date_str}"
                for attempt in range(2):
                    try:
                        res = await session.get(url, impersonate="chrome124", timeout=30)
                        if res.status_code == 200:
                            data = res.json()
                            events = data.get('events', [])
                            for event in events:
                                # use old parsing logic
                                game = await _parse_sofascore_event_from_raw(event, sport, start_ts, max_ts)
                                if game:
                                    # try to get tv data
                                    try:
                                        tv = await get_tv_data(session, event['id'])
                                        game['tv_channels'] = tv
                                    except:
                                        pass
                                    all_games.append(game)
                            break
                        elif res.status_code == 403:
                            await asyncio.sleep(3)
                    except:
                        break
                await asyncio.sleep(2)
    return all_games

# We need the old get_tv_data for fallback
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

# ================== CACHE SOFASCORE ==================
def load_sofascore_cache():
    try:
        with open(SOFASCORE_CACHE_FILE, 'r') as f:
            data = json.load(f)
            if data.get('date') == datetime.now().strftime("%Y-%m-%d"):
                return data.get('games', [])
    except:
        pass
    return None

def save_sofascore_cache(games):
    with open(SOFASCORE_CACHE_FILE, 'w') as f:
        json.dump({'date': datetime.now().strftime("%Y-%m-%d"), 'games': games}, f)

# ================== SECONDARY SOURCES ==================
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
        if "Tennis" in league or "Tenis" in league or "ATP" in league or "WTA" in league:
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
        if sport == "Tennis" or "Tennis" in league or "Tenis" in league:
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

# ================== CÁC NGUỒN MỚI TỪ GITHUB ==================
async def fetch_json(session, url):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                text = await resp.text()
                return json.loads(text)
            else:
                print(f"   ⚠️ Lỗi tải {url[:60]}... (HTTP {resp.status})")
                return None
    except Exception as e:
        print(f"   ❌ Lỗi tải {url[:60]}...: {e}")
        return None

def is_tennis_league(league: str) -> bool:
    if not league:
        return False
    league_lower = league.lower()
    tennis_keywords = ["atp", "wta", "tennis", "tenis", "masters", "open", "grand slam"]
    return any(keyword in league_lower for keyword in tennis_keywords)

def parse_hubsport(entry: dict) -> Optional[Dict]:
    try:
        if 'Date' not in entry or 'Time' not in entry:
            return None
        dt_str = f"{entry['Date']} {entry['Time']}"
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=TIMEZONE)
        kick_utc = int(dt.timestamp())
        league = entry.get('League', '')
        if is_tennis_league(league):
            league = "Tennis"
        elif "Premier League" in league:
            league = "Premier League"
        else:
            if DEBUG_MERGE:
                print(f"   [DEBUG] Bỏ qua league không hỗ trợ: '{league}'")
            return None
        if league not in ALLOWED_FOOTBALL_LEAGUES and league != "Tennis":
            return None
        match_raw = entry.get('Matchup', '')
        if not match_raw:
            return None
        match = match_raw.replace(' @ ', ' vs ')
        channels = entry.get('Services', [])
        if not channels:
            return None
        return {
            "league": league,
            "match": match,
            "kick_utc": kick_utc,
            "time": vn_time(kick_utc),
            "tv_channels": [{"country": "Hubsport", "channels": channels}],
            "source": "hubsport"
        }
    except Exception as e:
        if DEBUG_MERGE:
            print(f"   [DEBUG] Lỗi parse hubsport: {e}")
        return None

def parse_nowtv(entry: dict) -> Optional[Dict]:
    try:
        if 'Date' not in entry or 'Time' not in entry:
            return None
        dt_str = f"{entry['Date']} {entry['Time']}"
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=TIMEZONE)
        kick_utc = int(dt.timestamp())
        league = entry.get('League', '')
        if is_tennis_league(league):
            league = "Tennis"
        elif "Premier League" in league or "PREMIER LEAGUE" in league:
            league = "Premier League"
        else:
            if DEBUG_MERGE:
                print(f"   [DEBUG] Bỏ qua league NowTV không hỗ trợ: '{league}'")
            return None
        if league not in ALLOWED_FOOTBALL_LEAGUES and league != "Tennis":
            return None
        match_raw = entry.get('Matchup', '')
        if not match_raw:
            return None
        match = match_raw.replace(' @ ', ' vs ')
        channels = entry.get('Services', [])
        if not channels:
            return None
        return {
            "league": league,
            "match": match,
            "kick_utc": kick_utc,
            "time": vn_time(kick_utc),
            "tv_channels": [{"country": "NowTV", "channels": channels}],
            "source": "nowtv"
        }
    except Exception as e:
        if DEBUG_MERGE:
            print(f"   [DEBUG] Lỗi parse nowtv: {e}")
        return None

async def load_all_secondary_sources(start_ts: int, max_ts: int) -> List[Dict]:
    games = []
    for func, fname in [(parse_livesportsontv, "schedule_livesportsontv.json"),
                        (parse_wheresthematch, "results.json"),
                        (parse_ausport, "ausport_schedule.json")]:
        data = load_json_file(fname)
        for entry in data:
            g = func(entry)
            if g and start_ts <= g['kick_utc'] <= max_ts:
                games.append(g)

    remote_sources = [
        ("https://raw.githubusercontent.com/Love4vn/Live-Schedue/refs/heads/1/live_matches.json", parse_hubsport),
        ("https://raw.githubusercontent.com/Love4vn/Live-Schedue/refs/heads/1/nowtv_sports_schedule_en.json", parse_nowtv)
    ]

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_json(session, url) for url, _ in remote_sources]
        results = await asyncio.gather(*tasks)

        for (url, parser), data in zip(remote_sources, results):
            if data:
                for entry in data:
                    g = parser(entry)
                    if g and start_ts <= g['kick_utc'] <= max_ts:
                        games.append(g)

    if DEBUG_MERGE:
        sources = {}
        for g in games:
            src = g.get('source', 'unknown')
            sources[src] = sources.get(src, 0) + 1
        print(f"   📊 Số trận từ các nguồn: {sources}")

    return games

def merge_games(primary: List[Dict], secondary: List[Dict]) -> List[Dict]:
    primary_football = [g for g in primary if g['league'] != "Tennis"]
    primary_tennis = [g for g in primary if g['league'] == "Tennis"]
    secondary_football = [g for g in secondary if g['league'] != "Tennis"]
    secondary_tennis = [g for g in secondary if g['league'] == "Tennis"]

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

def extract_headers_from_extra(extra_lines):
    headers = {}
    if not extra_lines:
        return headers
    for line in extra_lines:
        line = line.strip()
        if line.startswith('#EXTVLCOPT'):
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

async def fetch_m3u_content(session, url):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            return await resp.text()
    except Exception as e:
        print(f"   Lỗi tải {url[:60]}...: {e}")
        return None

async def load_all_m3u_async(m3u_urls):
    all_channels = []
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_m3u_content(session, url) for url in m3u_urls]
        contents = await asyncio.gather(*tasks)
        for content in contents:
            if content:
                chs = parse_m3u(content)
                for ch in chs:
                    if re.search(r'#{3,}', ch.get('name', '')):
                        continue
                    if is_low_resolution(ch.get('name', '')):
                        continue
                    all_channels.append(ch)
    return all_channels

async def head_check(session, url, extra_headers=None):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    if extra_headers:
        headers.update(extra_headers)
    try:
        async with session.head(url, headers=headers, timeout=VALIDATE_TIMEOUT, allow_redirects=True) as resp:
            if resp.status == 404:
                return False
            return True
    except (asyncio.TimeoutError, aiohttp.ClientConnectorError):
        return False
    except Exception:
        return True

# ================== MAIN ==================
async def main():
    start_time = time.time()
    vn_now = datetime.now(TIMEZONE)
    start_ts = int(datetime.now(TIMEZONE).timestamp()) - 7200
    max_ts = int(datetime.now(TIMEZONE).timestamp()) + 86400

    print("🔄 Bắt đầu lấy lịch từ 2 GIỜ TRƯỚC đến 24 GIỜ TỚI...")

    # 1. SofaScore với cache
    cached_games = load_sofascore_cache()
    if cached_games:
        print("📦 Dùng cache SofaScore từ lần chạy trước.")
        sofascore_games = cached_games
    else:
        print("📡 Đang lấy dữ liệu từ SofaScore...")
        sofascore_games = await scrape_sofascore(start_ts, max_ts)
        save_sofascore_cache(sofascore_games)
    print(f"   ✅ SofaScore: {len(sofascore_games)} trận")

    # 2. Nguồn phụ
    print("📡 Đang đọc các nguồn JSON phụ (cục bộ + từ xa)...")
    secondary_games = await load_all_secondary_sources(start_ts, max_ts)
    print(f"   ✅ Các nguồn phụ: {len(secondary_games)} trận")

    all_games = merge_games(sofascore_games, secondary_games)

    # ================== GỘP TRẬN TRÙNG (≤30 PHÚT) ==================
    print("🔄 Đang gộp các trận trùng lặp (chương trình dạo đầu)...")

    def get_match_key(match_str: str, league: str) -> str:
        if league == "Tennis":
            clean = re.sub(r'[^\w\s]', ' ', match_str.lower())
            return ' '.join(clean.split())
        def simplify_team_name(name: str) -> str:
            name = name.strip().lower()
            name = re.sub(r'\b(fc|afc|sc|united|city|wanderers|rovers|athletic|albion|town|county|&|hove|and)\b', '', name)
            name = re.sub(r'[^\w\s]', ' ', name)
            name = ' '.join(name.split())
            parts = name.split()
            if len(parts) > 1:
                return parts[0]
            return name
        clean = match_str.lower()
        clean = re.sub(r'[-–—]', ' vs ', clean)
        clean = re.sub(r'\bvs\.?\b', ' vs ', clean)
        clean = re.sub(r'\bx\b', ' vs ', clean)
        parts = clean.split(' vs ')
        if len(parts) == 2:
            team1 = simplify_team_name(parts[0])
            team2 = simplify_team_name(parts[1])
            teams = sorted([team1, team2])
            return f"{teams[0]} vs {teams[1]}"
        return clean

    groups = {}
    for game in all_games:
        league = game['league']
        match_key = get_match_key(game['match'], league)
        key = (league, match_key)
        if key not in groups:
            groups[key] = []
        groups[key].append(game)

    deduped_games = []
    for (league, match_key), game_list in groups.items():
        if league == "Tennis":
            game_list.sort(key=lambda g: g['kick_utc'])
            clusters = []
            current_cluster = [game_list[0]]
            for g in game_list[1:]:
                if (g['kick_utc'] - current_cluster[-1]['kick_utc'] <= 1800 and
                    get_match_key(g['match'], league) == get_match_key(current_cluster[-1]['match'], league)):
                    current_cluster.append(g)
                else:
                    clusters.append(current_cluster)
                    current_cluster = [g]
            clusters.append(current_cluster)
            for cluster in clusters:
                if len(cluster) == 1:
                    deduped_games.append(cluster[0])
                else:
                    merged_game = cluster[0].copy()
                    merged_game['kick_utc'] = max(g['kick_utc'] for g in cluster)
                    merged_game['time'] = vn_time(merged_game['kick_utc'])
                    merged_channels = {}
                    for g in cluster:
                        for tv in g['tv_channels']:
                            country = tv['country']
                            if country not in merged_channels:
                                merged_channels[country] = set()
                            merged_channels[country].update(tv['channels'])
                    merged_game['tv_channels'] = [
                        {"country": c, "channels": list(chs)}
                        for c, chs in merged_channels.items()
                    ]
                    deduped_games.append(merged_game)
        else:
            if len(game_list) == 1:
                deduped_games.append(game_list[0])
                continue
            game_list.sort(key=lambda g: g['kick_utc'])
            clusters = []
            current_cluster = [game_list[0]]
            for g in game_list[1:]:
                if g['kick_utc'] - current_cluster[-1]['kick_utc'] <= 1800:
                    current_cluster.append(g)
                else:
                    clusters.append(current_cluster)
                    current_cluster = [g]
            clusters.append(current_cluster)
            for cluster in clusters:
                merged_game = cluster[0].copy()
                merged_game['kick_utc'] = max(g['kick_utc'] for g in cluster)
                merged_game['time'] = vn_time(merged_game['kick_utc'])
                merged_channels = {}
                for g in cluster:
                    for tv in g['tv_channels']:
                        country = tv['country']
                        if country not in merged_channels:
                            merged_channels[country] = set()
                        merged_channels[country].update(tv['channels'])
                merged_game['tv_channels'] = [
                    {"country": c, "channels": list(chs)}
                    for c, chs in merged_channels.items()
                ]
                deduped_games.append(merged_game)

    all_games = deduped_games
    print(f"   ✅ Sau khi gộp còn {len(all_games)} trận")

    if DEBUG_MERGE:
        tennis_count = sum(1 for g in all_games if g['league'] == 'Tennis')
        football_count = len(all_games) - tennis_count
        print(f"   🎾 Tennis: {tennis_count} trận, ⚽ Bóng đá: {football_count} trận")

    today_str = datetime.now().strftime("%Y%m%d")
    schedule = {today_str: {"date": datetime.now().strftime("%A, %d/%m"), "games": all_games}}
    output = {"updated": vn_now.strftime("%Y-%m-%d %H:%M VN"), "days": schedule}
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"✅ schedule.json: {len(all_games)} trận")

    # 3. Tải M3U
    print("📥 Đang tải playlist M3U bất đồng bộ...")
    m3u_urls = []
    try:
        with open(M3U_LIST_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and line.startswith('http'):
                    m3u_urls.append(line)
        print(f"   📋 Tìm thấy {len(m3u_urls)} URL trong M3U_list.txt")
    except Exception as e:
        print(f"   ❌ Lỗi đọc file M3U_list.txt: {e}")
        return

    all_channels = await load_all_m3u_async(m3u_urls)
    unique_ch = list({ch['url']: ch for ch in all_channels if ch.get('url')}.values())
    print(f"   ✅ Đã tải {len(unique_ch)} kênh")

    print("🔄 Đang match kênh với lịch...")
    live_events = []
    for g in all_games:
        try:
            used_urls = set()
            channel_count = 0
            for tv in g.get("tv_channels", []):
                tv_country = tv.get("country", "")
                for ch_name in tv.get("channels", []):
                    if channel_count >= MAX_CHANNELS_PER_MATCH:
                        break
                    matching = [ch for ch in unique_ch if is_channel_match(ch_name, ch['name'], tv_country)]
                    if DEBUG_MATCH and not matching:
                        print(f"   [DEBUG] Không match kênh: '{ch_name}' (country: {tv_country})")
                    for ch in matching:
                        if channel_count >= MAX_CHANNELS_PER_MATCH:
                            break
                        url = ch['url']
                        if url in used_urls:
                            continue
                        used_urls.add(url)
                        display_name = f"{g['time']} | {g['match']} ({ch_name})"
                        live_events.append({
                            "datetime": datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE),
                            "name": display_name,
                            "channel": ch,
                            "league": g["league"],
                            "country": tv_country,
                            "match": g["match"],
                            "kick_utc": g["kick_utc"]
                        })
                        channel_count += 1
                if channel_count >= MAX_CHANNELS_PER_MATCH:
                    break
            if channel_count == 0 and g['match']:
                match_norm = normalize(g['match'])
                for ch in unique_ch:
                    if is_team_match(match_norm, ch['name']):
                        url = ch['url']
                        if url in used_urls:
                            continue
                        used_urls.add(url)
                        display_name = f"{g['time']} | {g['match']} (M3U: {ch['name']})"
                        live_events.append({
                            "datetime": datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE),
                            "name": display_name,
                            "channel": ch,
                            "league": g["league"],
                            "country": "",
                            "match": g["match"],
                            "kick_utc": g["kick_utc"]
                        })
                        break
        except Exception as e:
            print(f"   Lỗi xử lý trận {g.get('match', '')}: {e}")
            continue

    print(f"   📺 Tổng số link sau khi match: {len(live_events)}")

    # 5. Validate HEAD (nếu bật)
    if ENABLE_VALIDATION:
        print("🔍 Kiểm tra nhanh HEAD...")
        async with aiohttp.ClientSession() as session:
            sem = asyncio.Semaphore(HEAD_CONCURRENCY)
            async def check_one(ev):
                async with sem:
                    extra = extract_headers_from_extra(ev['channel'].get('extra', []))
                    return await head_check(session, ev['channel']['url'], extra)
            results = await asyncio.gather(*[check_one(ev) for ev in live_events])
        validated_events = [ev for ev, ok in zip(live_events, results) if ok]
        print(f"   ✅ Còn lại {len(validated_events)} link (loại {len(live_events)-len(validated_events)})")
    else:
        print("⚡ Bỏ qua kiểm tra link (ENABLE_VALIDATION = False)")
        validated_events = live_events

    # 6. Ghi M3U
    tennis_events = [ev for ev in validated_events if ev['league'] == "Tennis"]
    other_events = [ev for ev in validated_events if ev['league'] != "Tennis"]
    grouped_tennis = {}
    for ev in tennis_events:
        key = (ev['channel']['url'], ev['league'])
        if key not in grouped_tennis:
            grouped_tennis[key] = ev
    final_events = other_events + list(grouped_tennis.values())

    final_events.sort(key=lambda x: x["datetime"])

    sorted_events = []
    for (kick_utc, match), group in groupby(final_events, key=lambda ev: (ev["kick_utc"], ev["match"])):
        group_list = list(group)
        group_list.sort(key=lambda ev: get_country_priority(ev.get("country", "")))
        sorted_events.extend(group_list)
    final_events = sorted_events

    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ev in final_events:
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

    elapsed = time.time() - start_time
    print(f"\n🎉 HOÀN THÀNH trong {elapsed:.1f} giây!")
    print(f"   • schedule.json: {len(all_games)} trận")
    print(f"   • live_schedule.m3u: {len(final_events)} kênh")

if __name__ == "__main__":
    asyncio.run(main())
