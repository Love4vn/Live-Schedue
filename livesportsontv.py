# File: livesportsontv.py
# Hoàn chỉnh: Tích hợp livesportsontv + footonsat, chuẩn hóa tên đội toàn diện, gộp trùng chính xác

import asyncio
import json
import re
import aiohttp
from datetime import datetime, timedelta, timezone
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# ==================== CẤU HÌNH ====================
VN_TZ = timezone(timedelta(hours=7))
TIME_RANGE_HOURS_BEFORE = 2
TIME_RANGE_HOURS_AFTER =26

# Danh sách các nguồn footonsat (bao gồm today.json)
FOOTONSAT_URLS = [
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/premierleague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/seriea.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/laliga.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/bundesliga.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/ligue1.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/championsleague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/europaleague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/ConferenceLeague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/today.json"  # Nguồn bổ sung
]

# ==================== HÀM TIỆN ÍCH ====================
def parse_time_with_ampm(time_str: str):
    """Chuyển '10:00 PM' sang 24h"""
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
        "tháng 11": 11, "tháng 12":12
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

# ==================== CHUẨN HÓA DỮ LIỆU ====================
def normalize_league(league: str) -> str:
    league_lower = league.lower()
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
    if "national womens soccer league" in league_lower or "nwsl" in league_lower:
        return "NWSL"
    if "major league soccer" in league_lower or "mls" in league_lower:
        return "MLS"
    if "argentinean primera división" in league_lower:
        return "Primera División Argentina"
    return league.strip()

# Bảng ánh xạ tên đội chuẩn (canonical) và các biến thể
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
    """Chuẩn hóa tên đội bóng bằng cách ánh xạ từ bảng mapping."""
    if not name:
        return name
    name_lower = name.lower().strip()
    # Loại bỏ "FC", "SC", "AS", "US", "AC", "SSC" nếu có
    name_lower = re.sub(r'\b(fc|sc|as|us|ac|ssc|sv|tsv|vfl)\b', '', name_lower)
    # Loại bỏ các ký tự đặc biệt
    name_lower = re.sub(r'[^\w\s]', '', name_lower)
    # Trim
    name_lower = name_lower.strip()
    # Kiểm tra trong bảng mapping (ưu tiên so khớp chính xác từng phần)
    best_match = name
    best_match_key = None
    # Tìm mapping có key xuất hiện trong name_lower
    for key, canonical in TEAM_NAME_MAPPING.items():
        if key in name_lower:
            # Nếu tìm thấy nhiều key, ưu tiên key dài nhất
            if best_match_key is None or len(key) > len(best_match_key):
                best_match_key = key
                best_match = canonical
    return best_match

def normalize_matchup(matchup: str):
    """
    Chuẩn hóa matchup thành tuple (đội khách chuẩn, đội nhà chuẩn).
    Nếu không parse được (tennis, ...) thì trả về chuỗi gốc.
    """
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
    else:
        return matchup  # không xác định được, trả về chuỗi gốc
    if not away or not home:
        return matchup
    # Chuẩn hóa tên đội
    away_norm = normalize_team_name(away)
    home_norm = normalize_team_name(home)
    return (away_norm, home_norm)

# ==================== LỌC GIAO HỮU (giữ nguyên) ====================
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

# ==================== CẤU HÌNH GIẢI (livesportsontv) ====================
LEAGUES_CONFIG = {
    # Giữ nguyên như cũ (các giải bóng đá, tennis...)
    # ...
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
                        league = normalize_league(current_match['compet'].strip())
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
    # Xử lý trận cuối
    if current_match:
        try:
            dt_utc = datetime.strptime(f"{current_match['date']} {current_match['time']}", "%Y-%m-%d %H:%M")
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
            dt_vn = dt_utc.astimezone(VN_TZ)
            if is_within_time_range(dt_vn, ref_time):
                league = normalize_league(current_match['compet'].strip())
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

# ==================== LIVESPORTSONTV ====================
async def scrape_livesportsontv(ref_time: datetime):
    # Giữ nguyên như code trước (không thay đổi)
    # ...
    pass

# ==================== MAIN ====================
async def main():
    ref_time = datetime.now(VN_TZ)
    print(f"🕒 Thời gian tham chiếu (VN): {ref_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏳ Khoảng: {TIME_RANGE_HOURS_BEFORE}h trước → {TIME_RANGE_HOURS_AFTER}h sau")

    games_live = await scrape_livesportsontv(ref_time)
    print(f"\n🏟️ Từ livesportsontv: {len(games_live)} trận")

    games_foot = await fetch_footonsat_data(ref_time)
    print(f"🛰️ Từ footonsat: {len(games_foot)} trận")

    # Gộp và loại trùng, ưu tiên footonsat
    unique = {}

    # Thêm footonsat trước
    for g in games_foot:
        norm_league = g["League"]
        norm_matchup_key = normalize_matchup(g["Matchup"])
        key = (g["Date"], g["Time"], norm_league, norm_matchup_key)
        unique[key] = {
            "Date": g["Date"],
            "Time": g["Time"],
            "League": g["League"],
            "Matchup": g["Matchup"],
            "Services": g["Services"]
        }

    # Thêm livesportsontv, nếu chưa có thì thêm, có thì gộp kênh
    for g in games_live:
        norm_league = g["League"]
        norm_matchup_key = normalize_matchup(g["Matchup"])
        key = (g["Date"], g["Time"], norm_league, norm_matchup_key)
        if key not in unique:
            unique[key] = {
                "Date": g["Date"],
                "Time": g["Time"],
                "League": g["League"],
                "Matchup": g["Matchup"],
                "Services": g["Services"]
            }
        else:
            existing_services = set(unique[key]["Services"])
            new_services = [s for s in g["Services"] if s not in existing_services]
            if new_services:
                unique[key]["Services"].extend(new_services)

    final = list(unique.values())
    final.sort(key=lambda x: (x["Date"], x["Time"]))

    with open("schedule_livesportsontv.json", "w", encoding="utf-8") as f:
        json.dump(final, f, indent=4, ensure_ascii=False)

    print(f"\n🎉 TỔNG KẾT: {len(final)} trận (đã gộp và loại trùng)")

if __name__ == "__main__":
    asyncio.run(main())
