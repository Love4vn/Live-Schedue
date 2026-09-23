# File: livesportsontv.py
# Hoàn chỉnh: scrape livesportsontv (DOM Next.js) + footonsat
# Đã bỏ NowStreams do API lỗi
# ✅ FIX: Lấy được kênh phát (channel chips) với 5 tầng fallback

import asyncio
import json
import re
import aiohttp
from datetime import datetime, timedelta, timezone
from playwright.async_api import async_playwright

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
    "ipswich town": "Ipswich Town",
    "ipswich": "Ipswich Town",
    "the tractor boys": "Ipswich Town",
    "coventry city": "Coventry City",
    "coventry": "Coventry City",
    "the sky blues": "Coventry City",
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

    # Đội tuyển quốc gia
    "germany": "Germany", "deutschland": "Germany", "nationalelf": "Germany",
    "dfb elf": "Germany", "die mannschaft": "Germany",
    "france": "France", "les bleus": "France",
    "england": "England", "three lions": "England",
    "spain": "Spain", "la roja": "Spain", "furias rojas": "Spain",
    "italy": "Italy", "squadra azzurra": "Italy",
    "portugal": "Portugal", "selecao das quinas": "Portugal",
    "netherlands": "Netherlands", "holland": "Netherlands", "oranje": "Netherlands",
    "belgium": "Belgium", "red devils": "Belgium",
    "croatia": "Croatia", "vatreni": "Croatia",
    "argentina": "Argentina", "albiceleste": "Argentina",
    "brazil": "Brazil", "selecao": "Brazil", "canarinho": "Brazil",
    "japan": "Japan", "blue samurai": "Japan",
    "south korea": "South Korea", "republic of korea": "South Korea",
    "tigers of asia": "South Korea",
    "usa": "United States", "usmnt": "United States",
    "the stars and stripes": "United States",
    "austria": "Austria", "wunderteam": "Austria",
    "czech republic": "Czech Republic", "czechia": "Czech Republic",
    "denmark": "Denmark", "danish dynamite": "Denmark",
    "poland": "Poland", "bialo-czerwoni": "Poland",
    "sweden": "Sweden", "blagult": "Sweden",
    "switzerland": "Switzerland", "nati": "Switzerland",
    "turkey": "Turkey", "ayyildizlilar": "Turkey",
    "russia": "Russia", "sbornaya": "Russia",
    "ukraine": "Ukraine", "z birna": "Ukraine",
    "serbia": "Serbia", "orlovi": "Serbia",
    "greece": "Greece", "pirasma": "Greece",
    "scotland": "Scotland", "tartan army": "Scotland",
    "wales": "Wales", "dragons": "Wales",
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
    "International Friendlies": {"url": "https://www.livesportsontv.com/league/international-friendly-2", "teams": None, "custom_filter": "friendly"},
    "FA Cup": {"url": "https://www.livesportsontv.com/league/fa-cup", "teams": None, "custom_filter": "premier_league_only"},
    "Carabao Cup": {"url": "https://www.livesportsontv.com/league/league-cup", "teams": None, "custom_filter": "premier_league_only"},

    # Tennis
    "Tennis (ATP)": {"url": "https://www.livesportsontv.com/league/atp/", "is_tennis": True},
    "Tennis (WTA)": {"url": "https://www.livesportsontv.com/league/wta/", "is_tennis": True},
    "Australian Open": {"url": "https://www.livesportsontv.com/league/australian-open", "is_tennis": True},
    "French Open": {"url": "https://www.livesportsontv.com/league/roland-garros", "is_tennis": True},
    "Wimbledon": {"url": "https://www.livesportsontv.com/league/wimbledon-tennis", "is_tennis": True},
    "US Open": {"url": "https://www.livesportsontv.com/league/us-open", "is_tennis": True}
}

# ==================== JAVASCRIPT EXTRACTOR (chạy trong browser) ====================
# Đây là script JS dùng để bóc tách DOM, tách riêng ra cho dễ đọc / bảo trì
EXTRACT_JS = r"""
() => {
    const output = [];

    // ============ HÀM BÓC KÊNH (5 TẦNG FALLBACK) ============
    const extractChannels = (eventElement) => {
        const channels = [];
        const seen = new Set();

        const add = (name, type, url) => {
            name = (name || '').replace(/\s+/g, ' ').trim();
            if (!name) return;
            // Bỏ alt rác của logo/team/icon
            const low = name.toLowerCase();
            if (['logo', 'image', 'icon', 'team logo', 'channel'].includes(low)) return;
            if (low.length < 2 || low.length > 80) return;
            if (seen.has(low)) return;
            seen.add(low);
            channels.push({ name, type: type || 'tv', sourceUrl: url || null });
        };

        // ---- Tầng 1: class chứa "channelChip" (không phân biệt prefix) ----
        let chips = Array.from(eventElement.querySelectorAll(
            '[class*="channelChip" i], [class*="ChannelChip"], [class*="channel-chip"]'
        ));
        // Chỉ giữ outer (loại bỏ chip lồng trong chip khác)
        chips = chips.filter(el =>
            !chips.some(other => other !== el && other.contains(el))
        );

        for (const el of chips) {
            let name = '';
            // Ưu tiên text của chip
            const textEl = el.querySelector(
                '[class*="channelChipText" i], [class*="ChannelChipText"]'
            );
            if (textEl) name = textEl.textContent || '';
            // Fallback: img alt
            if (!name) {
                const img = el.querySelector('img');
                name = img?.getAttribute('alt') || '';
            }
            // Fallback: toàn bộ text chip
            if (!name) name = el.textContent || '';

            const link = el.tagName === 'A' ? el : el.closest('a');
            const cls = (typeof el.className === 'string') ? el.className : '';
            const isNonStreaming = /nonStreaming|NonStreaming/.test(cls);
            add(name, isNonStreaming ? 'tv' : 'streaming', link?.href);
        }

        // ---- Tầng 2: link tới /channel/ ----
        if (channels.length === 0) {
            const links = eventElement.querySelectorAll('a[href*="/channel/"]');
            for (const link of links) {
                const img = link.querySelector('img');
                const name = link.textContent?.trim()
                          || img?.getAttribute('alt')?.trim()
                          || '';
                add(name, 'tv', link.href);
            }
        }

        // ---- Tầng 3: img alt có sprite hoặc class chứa 'channel' ----
        if (channels.length === 0) {
            const imgs = eventElement.querySelectorAll('img[alt]');
            for (const img of imgs) {
                const alt = img.getAttribute('alt')?.trim() || '';
                const src = img.getAttribute('src') || '';
                const cls = (typeof img.className === 'string') ? img.className : '';
                if (alt && (
                    src.includes('sprite') ||
                    src.includes('channel') ||
                    /channel/i.test(cls)
                )) {
                    add(alt, 'tv', img.closest('a')?.href);
                }
            }
        }

        // ---- Tầng 4: quét mọi a/span/div có class chứa 'channel' ----
        if (channels.length === 0) {
            const candidates = eventElement.querySelectorAll(
                'a[class*="channel" i], span[class*="channel" i], div[class*="channel" i]'
            );
            for (const el of candidates) {
                // Bỏ phần tử cha chứa quá nhiều con
                if (el.querySelectorAll('*').length > 5) continue;
                const name = el.textContent?.trim() || '';
                if (name && name.length < 60) {
                    const link = el.tagName === 'A' ? el : el.closest('a');
                    add(name, 'tv', link?.href);
                }
            }
        }

        // ---- Tầng 5: quét img alt tổng quát (bỏ logo team) ----
        if (channels.length === 0) {
            const imgs = eventElement.querySelectorAll('img[alt]');
            for (const img of imgs) {
                const alt = img.getAttribute('alt')?.trim() || '';
                if (!alt) continue;
                const low = alt.toLowerCase();
                // Bỏ alt team/logo
                if (low.includes('logo') || low.includes('team')) continue;
                const src = img.getAttribute('src') || '';
                // Chỉ nhận nếu ảnh nhỏ (chip kênh thường <= 100x100)
                if (img.naturalWidth && img.naturalWidth < 200) {
                    add(alt, 'tv', img.closest('a')?.href);
                }
            }
        }

        return channels;
    };

    // ============ QUÉT CÁC SỰ KIỆN ============
    const sportBlocks = [
        ...document.querySelectorAll('[class*="FixtureListBySport_sport__"]')
    ];

    if (sportBlocks.length > 0) {
        for (const sportBlock of sportBlocks) {
            const sport = sportBlock.querySelector(
                '[class*="SectionDivider_label__"]'
            )?.textContent?.trim() || "";
            const leagueCards = [
                ...sportBlock.querySelectorAll(':scope > [class*="Card_card__"]')
            ];
            for (const leagueCard of leagueCards) {
                const league = leagueCard.querySelector(
                    '[class*="LeagueCard_cardTitleLink__"]'
                )?.textContent?.trim() || "";
                const eventElements = [
                    ...leagueCard.querySelectorAll('[class*="FixtureItem_container__"]')
                ];
                for (const eventElement of eventElements) {
                    if (eventElement.getClientRects().length === 0) continue;
                    const link = eventElement.querySelector('a[href*="/match/"]');
                    const title = link?.getAttribute("aria-label")?.trim();
                    const href = link?.getAttribute("href");
                    const time = eventElement.querySelector(
                        '[class*="FixtureItem_time__"]'
                    )?.textContent?.trim() || "";
                    if (title && href && time) {
                        output.push({
                            sport, league, title, href, time,
                            channels: extractChannels(eventElement)
                        });
                    }
                }
            }
        }
    }

    // Fallback khi không có sportBlocks
    if (output.length === 0) {
        const items = document.querySelectorAll('[class*="FixtureItem_container__"]');
        for (const item of items) {
            const link = item.querySelector('a[href*="/match/"]');
            const title = link?.getAttribute("aria-label")?.trim();
            const href = link?.getAttribute("href");
            const time = item.querySelector('[class*="FixtureItem_time__"]')?.textContent?.trim() || "";
            if (title && href && time) {
                output.push({
                    sport: '', league: '', title, href, time,
                    channels: extractChannels(item)
                });
            }
        }
    }

    return output;
}
"""

# ==================== LIVESPORTSONTV SCRAPING ====================
async def scrape_livesportsontv(ref_time: datetime):
    """
    Scrape từng giải đấu trong LEAGUES_CONFIG, chạy song song (Semaphore 4).
    Dùng page.evaluate() để lấy dữ liệu từ DOM Next.js mới.
    """
    all_games = []
    semaphore = asyncio.Semaphore(4)

    async def scrape_one(league_name, cfg):
        async with semaphore:
            return await scrape_league(league_name, cfg, ref_time)

    tasks = [scrape_one(name, cfg) for name, cfg in LEAGUES_CONFIG.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            print(f"⚠️ Lỗi khi scrape một giải: {result}")
            continue
        if result:
            all_games.extend(result)

    return all_games


async def scrape_league(league_name: str, cfg: dict, ref_time: datetime):
    """Scrape một giải đấu cụ thể bằng Playwright + page.evaluate()."""
    url = cfg["url"]
    team_filter = cfg.get("teams")
    custom_filter = cfg.get("custom_filter")
    is_tennis = cfg.get("is_tennis", False)
    games = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            locale="en-US",
            timezone_id="Asia/Makassar",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()
        page.set_default_navigation_timeout(90000)
        page.set_default_timeout(45000)

        print(f"\n--- {league_name} ---")
        print(f"    URL: {url}")

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=90000)

            # Chờ container sự kiện
            try:
                await page.wait_for_selector(
                    '[class*="FixtureItem_container__"]',
                    timeout=30000
                )
            except Exception:
                print(f"    ⚠️ Không tìm thấy container sự kiện (timeout 30s)")
                try:
                    await page.wait_for_selector(
                        'a[href*="/match/"]',
                        timeout=15000
                    )
                except Exception:
                    print(f"    ⚠️ Cũng không tìm thấy link match → bỏ qua giải này")
                    await context.close()
                    await browser.close()
                    return []

            # ✅ FIX: Chờ thêm cho chip kênh render (Next.js render client-side)
            try:
                await page.wait_for_selector(
                    '[class*="channelChip" i], a[href*="/channel/"]',
                    timeout=8000
                )
            except Exception:
                # Không phải giải nào cũng có kênh → không sao
                pass

            # Cho JS render nốt (network idle-ish)
            await page.wait_for_timeout(1500)

            # Trích xuất dữ liệu
            raw_events = await page.evaluate(EXTRACT_JS)

            if not raw_events:
                print(f"    📊 0 sự kiện")
                await context.close()
                await browser.close()
                return []

            print(f"    📊 {len(raw_events)} sự kiện thô")

            # ✅ DEBUG: đếm số sự kiện có kênh
            events_with_channels = sum(1 for e in raw_events if e.get('channels'))
            print(f"    📺 Sự kiện có kênh: {events_with_channels}/{len(raw_events)}")

            # ✅ DEBUG: nếu không có kênh nào, dump event HTML đầu tiên để soi
            if events_with_channels == 0:
                try:
                    sample_html = await page.evaluate("""
                        () => {
                            const el = document.querySelector('[class*="FixtureItem_container__"]');
                            return el ? el.outerHTML.slice(0, 4000) : 'NO_ELEMENT';
                        }
                    """)
                    print(f"    🐞 DEBUG event HTML (4000 ký tự đầu):\n{sample_html}")
                except Exception as e:
                    print(f"    🐞 Debug lỗi: {e}")

            added = 0
            for raw in raw_events:
                try:
                    match = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)', raw['time'], re.IGNORECASE)
                    if not match:
                        continue
                    hour = int(match.group(1))
                    minute = int(match.group(2))
                    meridiem = match.group(3).upper()
                    if meridiem == 'PM' and hour != 12:
                        hour += 12
                    elif meridiem == 'AM' and hour == 12:
                        hour = 0

                    now_wita = ref_time
                    page_dt = datetime(now_wita.year, now_wita.month, now_wita.day, hour, minute)
                    page_dt = page_dt.replace(tzinfo=timezone(timedelta(hours=8)))
                    vn_dt = page_dt.astimezone(VN_TZ)

                    if not is_within_time_range(vn_dt, ref_time):
                        continue

                    matchup = raw['title']
                    league_raw = raw.get('league', '') or league_name
                    league_display = normalize_league(league_raw) if league_raw else league_name
                    if is_tennis:
                        if league_name in ["Australian Open", "French Open", "Wimbledon", "US Open"]:
                            league_display = "Tennis (Grand Slam)"
                        else:
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

                    # ✅ Xử lý kênh
                    channels = []
                    for ch in raw.get('channels', []):
                        name = (ch.get('name') or '').strip()
                        if name:
                            channels.append(name)
                    # Loại trùng, giữ thứ tự
                    channels = list(dict.fromkeys(channels))

                    games.append({
                        "Date": vn_dt.strftime("%Y-%m-%d"),
                        "Time": vn_dt.strftime("%H:%M"),
                        "League": league_display,
                        "Matchup": matchup,
                        "Services": channels
                    })
                    added += 1
                except Exception as e:
                    print(f"    ⚠️ Parse lỗi 1 event: {e}")
                    continue

            print(f"    ✅ Thêm {added} trận")
            await context.close()
            await browser.close()
            return games

        except Exception as e:
            print(f"    ❌ Lỗi scrape {league_name}: {e}")
            try:
                await context.close()
                await browser.close()
            except Exception:
                pass
            return []

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

# ==================== MAIN ====================
async def main():
    ref_time = datetime.now(VN_TZ)
    print(f"🕒 Thời gian tham chiếu (VN): {ref_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏳ Khoảng: {TIME_RANGE_HOURS_BEFORE}h trước → {TIME_RANGE_HOURS_AFTER}h sau")

    games_live = await scrape_livesportsontv(ref_time)
    print(f"\n🏟️ Từ livesportsontv: {len(games_live)} trận")

    games_foot = await fetch_footonsat_data(ref_time)
    print(f"🛰️ Từ footonsat: {len(games_foot)} trận")

    # Gộp và loại trùng
    unique = {}
    for g in games_foot + games_live:
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
