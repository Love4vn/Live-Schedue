# File: livesportsontv.py
# Hoàn chỉnh: scrape livesportsontv + footonsat
# Đã bỏ NowStreams do API lỗi

import asyncio
import json
import re
import aiohttp
from datetime import datetime, timedelta, timezone
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# ==================== CẤU HÌNH ====================
VN_TZ = timezone(timedelta(hours=7))
TIME_RANGE_HOURS_BEFORE = 4
TIME_RANGE_HOURS_AFTER = 72

FOOTONSAT_URLS = [
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/premierleague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/seriea.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/laliga.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/bundesliga.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/ligue1.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/championsleague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/europaleague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/ConferenceLeague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/worldcup.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/today.json"
]

# ==================== DANH SÁCH GIẢI ĐẤU ĐƯỢC PHÉP ====================
ALLOWED_LEAGUES = {
    "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "UEFA European Championship", "FIFA World Cup",
    "International Friendlies", "FA Cup", "Carabao Cup",
    "Tennis (ATP)", "Tennis (WTA)", "Tennis (Grand Slam)"
}

PREMIER_LEAGUE_TEAMS = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham",
    "hull city", "ipswich town", "coventry city"
}

ALLOWED_TEAMS_PER_LEAGUE = {
    "Premier League": PREMIER_LEAGUE_TEAMS,
    "Serie A": {"inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"},
    "La Liga": {"barcelona", "real madrid", "atletico madrid"},
    "Bundesliga": {"bayern munich", "borussia dortmund", "bayer leverkusen"},
    "Ligue 1": {"psg", "paris saint-germain", "marseille", "olympique marseille"},
    "FA Cup": PREMIER_LEAGUE_TEAMS,
    "Carabao Cup": PREMIER_LEAGUE_TEAMS,
    "UEFA Champions League": None,
    "UEFA Europa League": None,
    "UEFA Europa Conference League": None,
    "UEFA European Championship": None,
    "FIFA World Cup": None,
    "International Friendlies": None,
}

# ==================== HÀM TIỆN ÍCH ====================
def parse_time_with_ampm(time_str: str):
    time_str = time_str.strip().upper()
    if ' ' not in time_str and ('AM' in time_str or 'PM' in time_str):
        if 'AM' in time_str:
            time_str = time_str.replace('AM', ' AM')
        elif 'PM' in time_str:
            time_str = time_str.replace('PM', ' PM')
    parts = time_str.split()
    if len(parts) == 2:
        time_part, meridiem = parts
    else:
        time_part = parts[0]
        meridiem = None
    hour_min = time_part.split(':')
    hour = int(hour_min[0])
    minute = int(hour_min[1]) if len(hour_min) > 1 else 0
    if meridiem == 'PM' and hour != 12:
        hour += 12
    elif meridiem == 'AM' and hour == 12:
        hour = 0
    return hour, minute

def parse_date_from_text(text):
    text = text.strip().lower()
    match = re.search(r'(\d{1,2})\s+([a-zà-ỹ0-9\s]+)', text)
    if match:
        day = match.group(1)
        month_str = match.group(2).strip()
        return day, month_str
    return None, None

def get_month_number(month_str: str) -> int:
    month_str = month_str.lower()
    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        "tháng 1": 1, "tháng 2": 2, "tháng 3": 3, "tháng 4": 4, "tháng 5": 5,
        "tháng 6": 6, "tháng 7": 7, "tháng 8": 8, "tháng 9": 9, "tháng 10": 10,
        "tháng 11": 11, "tháng 12": 12
    }
    for k, v in month_map.items():
        if k in month_str:
            return v
    return 1

def extract_timezone_from_html(soup):
    text = soup.get_text()
    match = re.search(r'ALL TIME GMT([+-]\d+)', text, re.IGNORECASE)
    if match:
        offset = int(match.group(1))
        return timezone(timedelta(hours=offset))
    return timezone.utc

def is_within_time_range(dt: datetime, ref: datetime) -> bool:
    start = ref - timedelta(hours=TIME_RANGE_HOURS_BEFORE)
    end = ref + timedelta(hours=TIME_RANGE_HOURS_AFTER)
    return start <= dt <= end

def is_youth_or_women(matchup: str, league: str) -> bool:
    combined = f"{matchup} {league}".lower()
    women_keywords = [
        "women", "womens", "women's", "woman", "female", "frauen", "damen", "weiblich",
        "donne", "femminile", "mujeres", "femenino", "femenina", "femmes", "féminin",
        "féminine", "mulheres", "feminino", "vrouwen", "női", "kadın", "w/serie"
    ]
    youth_keywords = [
        "youth", "junior", "academy", "reserves", "reserve", "ii", "zweite", "second team",
        "sub", "u-", "under", "jugend", "juniorer", "giovanili", "primavera", "cantera",
        "filial", "jeunes", "espoirs", "jong", "beloften", "greek super"
    ]
    for kw in women_keywords:
        if kw in combined:
            return True
    for kw in youth_keywords:
        if kw in combined:
            return True
    return False

def normalize_league(league: str) -> str:
    league_lower = league.lower()
    if "fa cup" in league_lower:
        return "FA Cup"
    if "carabao cup" in league_lower or "league cup" in league_lower:
        return "Carabao Cup"
    if "premier league" in league_lower:
        return "Premier League"
    if "serie a" in league_lower:
        return "Serie A"
    if "la liga" in league_lower or "primera" in league_lower:
        return "La Liga"
    if "bundesliga" in league_lower:
        return "Bundesliga"
    if "ligue 1" in league_lower:
        return "Ligue 1"
    if "champions league" in league_lower:
        return "UEFA Champions League"
    if "europa league" in league_lower:
        return "UEFA Europa League"
    if "conference league" in league_lower:
        return "UEFA Europa Conference League"
    if "european championship" in league_lower or "euro" in league_lower:
        return "UEFA European Championship"
    if "world cup" in league_lower:
        return "FIFA World Cup"
    if "friendly" in league_lower:
        return "International Friendlies"
    if "atp" in league_lower:
        return "Tennis (ATP)"
    if "wta" in league_lower:
        return "Tennis (WTA)"
    if "grand slam" in league_lower or "australian open" in league_lower or "french open" in league_lower or "roland garros" in league_lower or "wimbledon" in league_lower or "us open" in league_lower:
        return "Tennis (Grand Slam)"
    return league.strip()

# ==================== BẢNG ÁNH XẠ TÊN ĐỘI ====================
TEAM_NAME_MAPPING = {
    # Premier League
    "manchester united": "Manchester United",
    "man utd": "Manchester United",
    "man united": "Manchester United",
    "manchester city": "Manchester City",
    "man city": "Manchester City",
    "arsenal": "Arsenal",
    "arsenal london": "Arsenal",
    "chelsea": "Chelsea",
    "chelsea london": "Chelsea",
    "liverpool": "Liverpool",
    "lfc": "Liverpool",
    "tottenham hotspur": "Tottenham Hotspur",
    "tottenham": "Tottenham Hotspur",
    "spurs": "Tottenham Hotspur",
    "aston villa": "Aston Villa",
    "villa": "Aston Villa",
    "newcastle united": "Newcastle United",
    "newcastle": "Newcastle United",
    "west ham united": "West Ham United",
    "west ham": "West Ham United",
    "the hammers": "West Ham United",
    "everton": "Everton",
    "the toffees": "Everton",
    "fulham": "Fulham",
    "the cottagers": "Fulham",
    "crystal palace": "Crystal Palace",
    "palace": "Crystal Palace",
    "eagles": "Crystal Palace",
    "brighton & hove albion": "Brighton",
    "brighton": "Brighton",
    "brentford": "Brentford",
    "the bees": "Brentford",
    "leeds united": "Leeds United",
    "leeds": "Leeds United",
    "wolverhampton wanderers": "Wolverhampton Wanderers",
    "wolves": "Wolverhampton Wanderers",
    "wolverhampton": "Wolverhampton Wanderers",
    "nottingham forest": "Nottingham Forest",
    "forest": "Nottingham Forest",
    "sunderland": "Sunderland",
    "black cats": "Sunderland",
    "leicester city": "Leicester City",
    "leicester": "Leicester City",
    "southampton": "Southampton",
    "saints": "Southampton",
    "burnley": "Burnley",
    "the clarets": "Burnley",
    "west bromwich albion": "West Brom",
    "west brom": "West Brom",
    # Ipswich Town
    "ipswich town": "Ipswich Town",
    "ipswich": "Ipswich Town",
    "the tractor boys": "Ipswich Town",

    # Coventry City
    "coventry city": "Coventry City",
    "coventry": "Coventry City",
    "the sky blues": "Coventry City",

    # Hull City
    "hull city": "Hull City",
    "hull": "Hull City",
    "the tigers": "Hull City",
    
    # Bundesliga
    "bayern munich": "Bayern Munich",
    "bayern münchen": "Bayern Munich",
    "bayern": "Bayern Munich",
    "borussia dortmund": "Borussia Dortmund",
    "dortmund": "Borussia Dortmund",
    "bvb": "Borussia Dortmund",
    "bayer leverkusen": "Bayer Leverkusen",
    "leverkusen": "Bayer Leverkusen",
    "rb leipzig": "RB Leipzig",
    "leipzig": "RB Leipzig",
    "borussia mönchengladbach": "Borussia Mönchengladbach",
    "mönchengladbach": "Borussia Mönchengladbach",
    "gladbach": "Borussia Mönchengladbach",
    "1. fc köln": "1. FC Köln",
    "fc köln": "1. FC Köln",
    "fc cologne": "1. FC Köln",
    "köln": "1. FC Köln",
    "cologne": "1. FC Köln",
    "eintracht frankfurt": "Eintracht Frankfurt",
    "frankfurt": "Eintracht Frankfurt",
    "vfb stuttgart": "VfB Stuttgart",
    "stuttgart": "VfB Stuttgart",
    "werder bremen": "Werder Bremen",
    "bremen": "Werder Bremen",
    "fc augsburg": "FC Augsburg",
    "augsburg": "FC Augsburg",
    "1899 hoffenheim": "1899 Hoffenheim",
    "hoffenheim": "1899 Hoffenheim",
    "fsv mainz 05": "Mainz 05",
    "mainz 05": "Mainz 05",
    "mainz": "Mainz 05",
    "hertha berlin": "Hertha Berlin",
    "hertha bsc": "Hertha Berlin",
    "union berlin": "Union Berlin",
    "vfl wolfsburg": "Wolfsburg",
    "wolfsburg": "Wolfsburg",
    "vfl bochum": "Bochum",
    "bochum": "Bochum",
    "darmstadt 98": "Darmstadt 98",
    "darmstadt": "Darmstadt 98",
    "fc heidenheim": "Heidenheim",
    "heidenheim": "Heidenheim",
    
    # La Liga
    "real madrid": "Real Madrid",
    "madrid": "Real Madrid",
    "los blancos": "Real Madrid",
    "fc barcelona": "Barcelona",
    "barcelona": "Barcelona",
    "barça": "Barcelona",
    "atletico madrid": "Atletico Madrid",
    "atlético madrid": "Atletico Madrid",
    "atletico": "Atletico Madrid",
    "atleti": "Atletico Madrid",
    "colchoneros": "Atletico Madrid",
    "real sociedad": "Real Sociedad",
    "real betis": "Real Betis",
    "betis": "Real Betis",
    "athletic bilbao": "Athletic Bilbao",
    "bilbao": "Athletic Bilbao",
    "valencia": "Valencia",
    "valencia cf": "Valencia",
    "villarreal": "Villarreal",
    "yellow submarine": "Villarreal",
    "sevilla": "Sevilla",
    "sevilla fc": "Sevilla",
    "getafe": "Getafe",
    "getafe cf": "Getafe",
    "espanyol": "Espanyol",
    "rcd espanyol": "Espanyol",
    "osasuna": "Osasuna",
    "ca osasuna": "Osasuna",
    "granada": "Granada",
    "granada cf": "Granada",
    "cadiz": "Cadiz",
    "cadiz cf": "Cadiz",
    "rayo vallecano": "Rayo Vallecano",
    "rayo": "Rayo Vallecano",
    "elche": "Elche",
    "elche cf": "Elche",
    "alaves": "Alaves",
    "deportivo alaves": "Alaves",
    "mallorca": "Mallorca",
    "rcd mallorca": "Mallorca",
    "girona": "Girona",
    "girona fc": "Girona",
    "celta vigo": "Celta Vigo",
    "celta": "Celta Vigo",
    
    # Serie A
    "ac milan": "AC Milan",
    "milan": "AC Milan",
    "rossoneri": "AC Milan",
    "inter milan": "Inter Milan",
    "inter": "Inter Milan",
    "nerazzurri": "Inter Milan",
    "juventus": "Juventus",
    "juve": "Juventus",
    "bianconeri": "Juventus",
    "vecchia signora": "Juventus",
    "napoli": "Napoli",
    "partenopei": "Napoli",
    "ssc napoli": "Napoli",
    "roma": "Roma",
    "giallorossi": "Roma",
    "as roma": "Roma",
    "lazio": "Lazio",
    "biancocelesti": "Lazio",
    "ss lazio": "Lazio",
    "atalanta": "Atalanta",
    "la dea": "Atalanta",
    "bergamo": "Atalanta",
    "fiorentina": "Fiorentina",
    "viola": "Fiorentina",
    "acf fiorentina": "Fiorentina",
    "torino": "Torino",
    "il toro": "Torino",
    "granata": "Torino",
    "bologna": "Bologna",
    "rossoblu": "Bologna",
    "udinese": "Udinese",
    "bianconeri friulani": "Udinese",
    "genoa": "Genoa",
    "grifone": "Genoa",
    "sampdoria": "Sampdoria",
    "blucerchiati": "Sampdoria",
    "verona": "Hellas Verona",
    "hellas verona": "Hellas Verona",
    "gialloblu": "Hellas Verona",
    "lecce": "Lecce",
    "giallorossi salentini": "Lecce",
    "salernitana": "Salernitana",
    "granata campani": "Salernitana",
    "monza": "Monza",
    "brianzoli": "Monza",
    "cremonese": "Cremonese",
    "grigiorossi": "Cremonese",
    "empoli": "Empoli",
    "azzurri": "Empoli",
    "spezia": "Spezia",
    "aquilotti": "Spezia",
    
    # Ligue 1
    "psg": "Paris Saint-Germain",
    "paris saint-germain": "Paris Saint-Germain",
    "paris st germain": "Paris Saint-Germain",
    "paris sg": "Paris Saint-Germain",
    "olympique marseille": "Marseille",
    "marseille": "Marseille",
    "om": "Marseille",
    "olympique lyon": "Lyon",
    "lyon": "Lyon",
    "ol": "Lyon",
    "as monaco": "Monaco",
    "monaco": "Monaco",
    "loscilly": "Monaco",
    "losc lille": "Lille",
    "lille": "Lille",
    "loscilly": "Lille",
    "ogc nice": "Nice",
    "nice": "Nice",
    "fc nantes": "Nantes",
    "nantes": "Nantes",
    "rc lens": "Lens",
    "lens": "Lens",
    "stade rennais": "Rennes",
    "rennes": "Rennes",
    "srfc": "Rennes",
    "montpellier": "Montpellier",
    "mhsc": "Montpellier",
    "clermont foot": "Clermont",
    "clermont": "Clermont",
    "strasbourg": "Strasbourg",
    "rc strasbourg": "Strasbourg",
    "angers": "Angers",
    "angers sco": "Angers",
    "sco": "Angers",
    "brest": "Brest",
    "stade brestois": "Brest",
    "toulouse": "Toulouse",
    "tfc": "Toulouse",
    "stade de reims": "Reims",
    "reims": "Reims",
    "fc metz": "Metz",
    "metz": "Metz",
    "ajaccio": "Ajaccio",
    "ac ajaccio": "Ajaccio",
    "auxerre": "Auxerre",
    "aja": "Auxerre",
    
    # Giải vô địch thế giới và các đội tuyển quốc gia
    "germany": "Germany",
    "deutschland": "Germany",
    "nationalelf": "Germany",
    "dfb elf": "Germany",
    "die mannschaft": "Germany",
    "france": "France",
    "les bleus": "France",
    "england": "England",
    "three lions": "England",
    "spain": "Spain",
    "la roja": "Spain",
    "furias rojas": "Spain",
    "italy": "Italy",
    "azzurri": "Italy",
    "squadra azzurra": "Italy",
    "portugal": "Portugal",
    "selecao das quinas": "Portugal",
    "netherlands": "Netherlands",
    "holland": "Netherlands",
    "oranje": "Netherlands",
    "belgium": "Belgium",
    "red devils": "Belgium",
    "croats": "Croatia",
    "vatreni": "Croatia",
    "argentina": "Argentina",
    "albiceleste": "Argentina",
    "brazil": "Brazil",
    "selecao": "Brazil",
    "canarinho": "Brazil",
    "japan": "Japan",
    "blue samurai": "Japan",
    "south korea": "South Korea",
    "republic of korea": "South Korea",
    "tigers of asia": "South Korea",
    "usa": "United States",
    "usmnt": "United States",
    "the stars and stripes": "United States",
    
    # European National Teams
    "austria": "Austria",
    "wunderteam": "Austria",
    "czech republic": "Czech Republic",
    "czechia": "Czech Republic",
    "denmark": "Denmark",
    "danish dynamite": "Denmark",
    "poland": "Poland",
    "bialo-czerwoni": "Poland",
    "sweden": "Sweden",
    "blagult": "Sweden",
    "switzerland": "Switzerland",
    "nati": "Switzerland",
    "turkey": "Turkey",
    "ayyildizlilar": "Turkey",
    "russia": "Russia",
    "sbornaya": "Russia",
    "ukraine": "Ukraine",
    "z birna": "Ukraine",
    "serbia": "Serbia",
    "orlovi": "Serbia",
    "greece": "Greece",
    "pirasma": "Greece",
    "scotland": "Scotland",
    "tartan army": "Scotland",
    "wales": "Wales",
    "dragons": "Wales",
}

def normalize_team_name(name: str) -> str:
    if not name:
        return name
    name_lower = name.lower().strip()
    name_lower = re.sub(r'\b(fc|sc|as|us|ac|ssc|sv|tsv|vfl|cf|cd)\b', '', name_lower)
    name_lower = re.sub(r'[^\w\s]', '', name_lower).strip()
    best_match = name
    best_len = 0
    for key, canonical in TEAM_NAME_MAPPING.items():
        if key in name_lower and len(key) > best_len:
            best_len = len(key)
            best_match = canonical
    return best_match

def normalize_matchup(matchup: str):
    matchup = matchup.strip()
    home = away = None
    if '@' in matchup:
        parts = [p.strip() for p in matchup.split('@')]
        if len(parts) == 2:
            away, home = parts
    elif 'vs' in matchup.lower():
        parts = [p.strip() for p in re.split(r'\s+vs\s+', matchup, flags=re.IGNORECASE)]
        if len(parts) == 2:
            home, away = parts
    if not away or not home:
        return matchup
    away_norm = normalize_team_name(away)
    home_norm = normalize_team_name(home)
    return (away_norm, home_norm)

def is_match_allowed(league: str, matchup: str) -> bool:
    if league not in ALLOWED_LEAGUES:
        return False
    if league == "International Friendlies":
        return True
    allowed_teams = ALLOWED_TEAMS_PER_LEAGUE.get(league)
    if allowed_teams is None:
        return True
    matchup_lower = matchup.lower()
    return any(team in matchup_lower for team in allowed_teams)

# ==================== BỘ LỌC GIAO HỮU ====================
EUROPEAN_COUNTRIES = {
    "albania", "andorra", "armenia", "austria", "azerbaijan", "belarus", "belgium", "bosnia",
    "bulgaria", "croatia", "cyprus", "czech", "denmark", "england", "estonia", "faroe",
    "finland", "france", "georgia", "germany", "gibraltar", "greece", "hungary", "iceland",
    "israel", "italy", "kazakhstan", "kosovo", "latvia", "liechtenstein", "lithuania",
    "luxembourg", "malta", "moldova", "monaco", "montenegro", "netherlands", "north macedonia",
    "northern ireland", "norway", "poland", "portugal", "republic of ireland", "romania",
    "russia", "san marino", "scotland", "serbia", "slovakia", "slovenia", "spain", "sweden",
    "switzerland", "turkey", "ukraine", "wales"
}
AMERICAS_TEAMS = {"argentina", "brazil"}
ASIA_TEAMS = {"japan", "south korea"}

def include_friendly_match(home: str, away: str) -> bool:
    home_low = home.lower()
    away_low = away.lower()
    if any(c in home_low or c in away_low for c in EUROPEAN_COUNTRIES):
        return True
    if any(c in home_low or c in away_low for c in AMERICAS_TEAMS):
        return True
    if any(c in home_low or c in away_low for c in ASIA_TEAMS):
        return True
    return False

def has_premier_league_team(matchup: str) -> bool:
    return any(team in matchup.lower() for team in PREMIER_LEAGUE_TEAMS)

# ==================== CẤU HÌNH GIẢI LIVESPORTSONTV ====================
LEAGUES_CONFIG = {
    # Bóng đá
    "Premier League": {"url": "https://www.livesportsontv.com/league/premier-league", "teams": PREMIER_LEAGUE_TEAMS},
    "Serie A": {"url": "https://www.livesportsontv.com/league/serie-a", "teams": {"inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"}},
    "La Liga": {"url": "https://www.livesportsontv.com/league/la-liga", "teams": {"barcelona", "real madrid", "atletico madrid"}},
    "Bundesliga": {"url": "https://www.livesportsontv.com/league/bundesliga-5", "teams": {"bayern", "borussia dortmund", "bayer leverkusen"}},
    "Ligue 1": {"url": "https://www.livesportsontv.com/league/ligue-1-3", "teams": {"psg", "marseille"}},
    "UEFA Champions League": {"url": "https://www.livesportsontv.com/league/uefa-champions-league", "teams": None},
    "UEFA Europa League": {"url": "https://www.livesportsontv.com/league/uefa-europa-league", "teams": None},
    "UEFA Europa Conference League": {"url": "https://www.livesportsontv.com/league/uefa-conference-league", "teams": None},
    "UEFA European Championship": {"url": "https://www.livesportsontv.com/league/uefa-european-championship", "teams": None},
    "FIFA World Cup": {"url": "https://www.livesportsontv.com/league/world-cup-5", "teams": None},
    "International Friendlies": {"url": "https://www.livesportsontv.com/league/friendly", "teams": None, "custom_filter": "friendly"},
    "FA Cup": {"url": "https://www.livesportsontv.com/league/fa-cup", "teams": None, "custom_filter": "premier_league_only"},
    "Carabao Cup": {"url": "https://www.livesportsontv.com/league/carabao-cup", "teams": None, "custom_filter": "premier_league_only"},
    # Tennis – Cập nhật URL mới
    "Tennis (ATP)": {"url": "https://www.livesportsontv.com/league/atp/", "is_tennis": True},
    "Tennis (WTA)": {"url": "https://www.livesportsontv.com/league/wta/", "is_tennis": True},
    "Australian Open": {"url": "https://www.livesportsontv.com/league/grand-slam/australian-open/", "is_tennis": True},
    "French Open": {"url": "https://www.livesportsontv.com/league/roland-garros", "is_tennis": True},
    "Wimbledon": {"url": "https://www.livesportsontv.com/league/wimbledon-tennis", "is_tennis": True},
    "US Open": {"url": "https://www.livesportsontv.com/league/us-open", "is_tennis": True}
}

# ==================== FOOTONSAT ====================
async def fetch_footonsat_data(ref_time: datetime):
    all_matches = []
    async with aiohttp.ClientSession() as session:
        for url in FOOTONSAT_URLS:
            try:
                async with session.get(url, timeout=30) as resp:
                    if resp.status != 200:
                        print(f"⚠️ {url.split('/')[-1]} -> HTTP {resp.status}")
                        continue
                    text = await resp.text()
                    data = json.loads(text)
                    items = data.get("footonsat", [])
                    matches = parse_footonsat_items(items, ref_time)
                    all_matches.extend(matches)
                    print(f"📡 {url.split('/')[-1]}: {len(matches)} trận")
            except Exception as e:
                print(f"⚠️ Lỗi fetch {url.split('/')[-1]}: {e}")
    return all_matches

def parse_footonsat_items(items, ref_time):
    matches = []
    current_match = None
    current_channels = []
    for item in items:
        if "match" in item and "compet" in item:
            if current_match:
                try:
                    dt_utc = datetime.strptime(f"{current_match['date']} {current_match['time']}", "%Y-%m-%d %H:%M")
                    dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                    dt_vn = dt_utc.astimezone(VN_TZ)
                    if is_within_time_range(dt_vn, ref_time):
                        league_raw = current_match['compet'].strip()
                        if not is_youth_or_women(current_match['match'], league_raw):
                            league = normalize_league(league_raw)
                            if is_match_allowed(league, current_match['match']):
                                matches.append({
                                    "Date": dt_vn.strftime("%Y-%m-%d"),
                                    "Time": dt_vn.strftime("%H:%M"),
                                    "League": league,
                                    "Matchup": current_match['match'].strip(),
                                    "Services": current_channels.copy()
                                })
                except Exception:
                    pass
            current_match = item
            current_channels = []
        elif "channel" in item and current_match and item.get("related_to", "").strip() == current_match['match'].strip():
            ch_name = item['channel'].strip()
            ch_name = re.sub(r'[📺]', '', ch_name).strip()
            if ch_name:
                current_channels.append(ch_name)
    if current_match:
        try:
            dt_utc = datetime.strptime(f"{current_match['date']} {current_match['time']}", "%Y-%m-%d %H:%M")
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
            dt_vn = dt_utc.astimezone(VN_TZ)
            if is_within_time_range(dt_vn, ref_time):
                league_raw = current_match['compet'].strip()
                if not is_youth_or_women(current_match['match'], league_raw):
                    league = normalize_league(league_raw)
                    if is_match_allowed(league, current_match['match']):
                        matches.append({
                            "Date": dt_vn.strftime("%Y-%m-%d"),
                            "Time": dt_vn.strftime("%H:%M"),
                            "League": league,
                            "Matchup": current_match['match'].strip(),
                            "Services": current_channels
                        })
        except Exception:
            pass
    return matches

# ==================== LIVESPORTSONTV SCRAPING (cập nhật xử lý nút "more") ====================
async def scrape_livesportsontv(ref_time: datetime):
    all_games = []
    current_year = ref_time.year

    # Hàm xử lý một giải đấu (sẽ chạy song song)
    async def process_league(league_name, cfg):
        url = cfg["url"]
        team_filter = cfg.get("teams")
        custom_filter = cfg.get("custom_filter")
        is_tennis = cfg.get("is_tennis", False)
        print(f"\n--- {league_name} ---")
        print(f"    URL: {url}")

        # Mở trình duyệt mới cho mỗi giải (nếu chạy song song)
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
            )
            page = await browser.new_page()
            page.set_default_navigation_timeout(60000)
            page.set_default_timeout(30000)

            try:
                # 1. Load trang với domcontentloaded, không đợi networkidle
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"    ❌ Lỗi tải trang: {e}")
                await browser.close()
                return []

            # 2. Chờ selector sự kiện xuất hiện (tối đa 20s)
            try:
                await page.wait_for_selector('.event--wrapp', timeout=20000)
            except:
                print(f"    ⚠️ Không tìm thấy sự kiện, bỏ qua giải này")
                await browser.close()
                return []

            # 3. Click các nút "more"
            try:
                more_buttons = await page.query_selector_all(
                    'button:has-text("more"), button:has-text("More"), a:has-text("more"), a:has-text("More")'
                )
                for btn in more_buttons:
                    try:
                        await btn.click()
                        await page.wait_for_timeout(1000)  # giảm xuống 1s
                    except:
                        pass
                show_more = await page.query_selector_all(
                    'a:has-text("Show more"), button:has-text("Show more")'
                )
                for btn in show_more:
                    try:
                        await btn.click()
                        await page.wait_for_timeout(1000)
                    except:
                        pass
            except:
                pass

            # 4. Cuộn trang (chỉ 3 lần)
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

            html = await page.content()
            await browser.close()

            soup = BeautifulSoup(html, 'html.parser')
            page_tz = extract_timezone_from_html(soup)
            rows = soup.find_all('div', class_='event--wrapp')
            print(f"    📊 {len(rows)} sự kiện")

            games = []
            for row in rows:
                try:
                    # (toàn bộ logic parse giữ nguyên như cũ)
                    date_div = row.find('div', class_='event__info--date')
                    if not date_div:
                        continue
                    date_text = date_div.get_text(separator=' ').strip()
                    day_str, month_str = parse_date_from_text(date_text)
                    if not day_str or not month_str:
                        day_tag = date_div.find('b')
                        month_tag = date_div.find('span')
                        if day_tag and month_tag:
                            day_str = day_tag.get_text(strip=True)
                            month_str = month_tag.get_text(strip=True).lower()
                    if not day_str or not month_str:
                        continue

                    month_num = get_month_number(month_str)
                    day_num = int(day_str)

                    time_tag = row.find('time')
                    if not time_tag:
                        continue
                    time_str = time_tag.get_text(strip=True)
                    try:
                        hour, minute = parse_time_with_ampm(time_str)
                    except:
                        continue

                    page_dt = datetime(current_year, month_num, day_num, hour, minute)
                    page_dt = page_dt.replace(tzinfo=page_tz)
                    vn_dt = page_dt.astimezone(VN_TZ)

                    if not is_within_time_range(vn_dt, ref_time):
                        continue

                    # Lấy tên trận
                    if is_tennis:
                        home_elem = row.find('div', class_=lambda c: c and 'event_participant--home' in c)
                        if not home_elem:
                            home_elem = row.find('div', class_='event__participant--home')
                        if home_elem:
                            matchup = home_elem.get_text(strip=True)
                        else:
                            title_elem = row.find('a', class_='event__title')
                            matchup = title_elem.get_text(strip=True) if title_elem else "Tennis Match"
                        if league_name in ["Australian Open", "French Open", "Wimbledon", "US Open"]:
                            league_display = "Tennis (Grand Slam)"
                        else:
                            league_display = league_name
                    else:
                        home_elem = row.find('div', class_=lambda c: c and 'event__participant--home' in c)
                        away_elem = row.find('div', class_=lambda c: c and 'event__participant--away' in c)
                        home = home_elem.get_text(strip=True) if home_elem else "?"
                        away = away_elem.get_text(strip=True) if away_elem else "?"
                        matchup = f"{away} @ {home}"
                        if home == "?" and away == "?":
                            title_elem = row.find('a', class_='event__title')
                            if title_elem:
                                matchup = title_elem.get_text(strip=True)
                        league_display = league_name

                    if is_youth_or_women(matchup, league_display):
                        continue

                    if team_filter is not None:
                        if not any(t.lower() in matchup.lower() for t in team_filter):
                            continue
                    if custom_filter == "premier_league_only":
                        if not has_premier_league_team(matchup):
                            continue
                    elif custom_filter == "friendly":
                        parts = matchup.split(' @ ')
                        if len(parts) == 2:
                            away, home = parts
                        else:
                            home, away = "?", "?"
                        if not include_friendly_match(home, away):
                            continue

                    # Lấy kênh
                    channels = []
                    tags_container = row.find('ul', class_='event__tags')
                    if not tags_container:
                        tags_container = row.find('div', class_='event__tags')
                    if tags_container:
                        for link in tags_container.find_all('a'):
                            aria = link.get('aria-label')
                            if aria:
                                channels.append(aria.strip())
                            else:
                                text = link.get_text(strip=True)
                                if text:
                                    channels.append(text)

                    if not channels:
                        for a_tag in row.find_all('a'):
                            text = a_tag.get_text(strip=True)
                            if text and len(text) > 2 and text.lower() not in ['more', 'watch', 'live', 'stream', 'buy', 'tickets']:
                                channels.append(text)

                    channel_selectors = [
                        '.event__channel', '.channel-name', '.service-name',
                        '.broadcaster', '.tv-channel', '[class*="channel"]',
                        '[class*="service"]', '[class*="broadcast"]'
                    ]
                    for selector in channel_selectors:
                        for elem in row.select(selector):
                            text = elem.get_text(strip=True)
                            if text and len(text) > 1 and text not in channels:
                                channels.append(text)

                    channels = list(dict.fromkeys(channels))

                    games.append({
                        "Date": vn_dt.strftime("%Y-%m-%d"),
                        "Time": vn_dt.strftime("%H:%M"),
                        "League": league_display,
                        "Matchup": matchup,
                        "Services": channels
                    })
                except Exception:
                    continue

            print(f"    ✅ Thêm {len(games)} trận")
            return games

    # Chạy tuần tự (cũ) – nếu bạn muốn nhanh hơn, dùng gather bên dưới
    for league_name, cfg in LEAGUES_CONFIG.items():
        games = await process_league(league_name, cfg)
        all_games.extend(games)

    # ==== NẾU MUỐN CHẠY SONG SONG, thay đoạn for bằng code này ====
    # tasks = []
    # for league_name, cfg in LEAGUES_CONFIG.items():
    #     tasks.append(process_league(league_name, cfg))
    # results = await asyncio.gather(*tasks)
    # for games in results:
    #     all_games.extend(games)

    return all_games
# ==================== MAIN ====================
async def main():
    ref_time = datetime.now(VN_TZ)
    print(f"🕒 Thời gian tham chiếu (VN): {ref_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏳ Khoảng: {TIME_RANGE_HOURS_BEFORE}h trước → {TIME_RANGE_HOURS_AFTER}h sau")

    games_live = await scrape_livesportsontv(ref_time)
    print(f"\n🏟️ Từ livesportsontv: {len(games_live)} trận")

    games_foot = await fetch_footonsat_data(ref_time)
    print(f"🛰️ Từ footonsat: {len(games_foot)} trận")

    # Đã bỏ nowstreams do API lỗi
    # games_now = await fetch_nowstreams_data(ref_time)
    # print(f"📺 Từ nowstreams: {len(games_now)} trận")

    # Gộp và loại trùng
    unique = {}
    for g in games_foot + games_live:  # chỉ còn 2 nguồn
        norm_league = normalize_league(g["League"])
        norm_key = normalize_matchup(g["Matchup"])
        key = (g["Date"], g["Time"], norm_league, norm_key)
        if key not in unique:
            unique[key] = {
                "Date": g["Date"],
                "Time": g["Time"],
                "League": norm_league,
                "Matchup": g["Matchup"],
                "Services": g["Services"]
            }
        else:
            existing = set(unique[key]["Services"])
            new_services = [s for s in g["Services"] if s not in existing]
            if new_services:
                unique[key]["Services"].extend(new_services)

    final = list(unique.values())
    final.sort(key=lambda x: (x["Date"], x["Time"]))

    with open("schedule_livesportsontv.json", "w", encoding="utf-8") as f:
        json.dump(final, f, indent=4, ensure_ascii=False)

    print(f"\n🎉 TỔNG KẾT: {len(final)} trận (đã gộp và loại trùng)")

if __name__ == "__main__":
    asyncio.run(main())
