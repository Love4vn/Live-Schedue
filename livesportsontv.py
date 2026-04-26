# File: livesportsontv.py
# Hoàn chỉnh: Tích hợp livesportsontv + footonsat, chuẩn hóa tên đội toàn diện, gộp trùng chính xác
# Bổ sung FA Cup và Carabao Cup

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
TIME_RANGE_HOURS_AFTER = 26

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
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/today.json"
]

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
    return league.strip()

# Bảng ánh xạ tên đội chuẩn (canonical) và các biến thể
TEAM_NAME_MAPPING = {
    # Premier League
    "manchester united": "Manchester United", "man utd": "Manchester United",
    "man united": "Manchester United", "manchester city": "Manchester City",
    "man city": "Manchester City", "arsenal": "Arsenal", "arsenal london": "Arsenal",
    "chelsea": "Chelsea", "chelsea london": "Chelsea", "liverpool": "Liverpool",
    "lfc": "Liverpool", "tottenham hotspur": "Tottenham Hotspur", "tottenham": "Tottenham Hotspur",
    "spurs": "Tottenham Hotspur", "aston villa": "Aston Villa", "villa": "Aston Villa",
    "newcastle united": "Newcastle United", "newcastle": "Newcastle United",
    "west ham united": "West Ham United", "west ham": "West Ham United", "everton": "Everton",
    "fulham": "Fulham", "crystal palace": "Crystal Palace", "palace": "Crystal Palace",
    "brighton & hove albion": "Brighton", "brighton": "Brighton", "brentford": "Brentford",
    "leeds united": "Leeds United", "leeds": "Leeds United", "wolverhampton wanderers": "Wolverhampton Wanderers",
    "wolves": "Wolverhampton Wanderers", "wolverhampton": "Wolverhampton Wanderers",
    "nottingham forest": "Nottingham Forest", "forest": "Nottingham Forest", "sunderland": "Sunderland",
    "leicester city": "Leicester City", "leicester": "Leicester City", "southampton": "Southampton",
    # Bundesliga
    "bayern munich": "Bayern Munich", "bayern münchen": "Bayern Munich", "bayern": "Bayern Munich",
    "borussia dortmund": "Borussia Dortmund", "dortmund": "Borussia Dortmund", "bayer leverkusen": "Bayer Leverkusen",
    "leverkusen": "Bayer Leverkusen", "rb leipzig": "RB Leipzig", "leipzig": "RB Leipzig",
    "borussia mönchengladbach": "Borussia Mönchengladbach", "mönchengladbach": "Borussia Mönchengladbach",
    "1. fc köln": "1. FC Köln", "fc köln": "1. FC Köln", "fc cologne": "1. FC Köln", "köln": "1. FC Köln",
    # La Liga
    "real madrid": "Real Madrid", "madrid": "Real Madrid", "fc barcelona": "Barcelona", "barcelona": "Barcelona",
    "atletico madrid": "Atletico Madrid", "atlético madrid": "Atletico Madrid", "real sociedad": "Real Sociedad",
    "real betis": "Real Betis", "betis": "Real Betis", "athletic bilbao": "Athletic Bilbao", "bilbao": "Athletic Bilbao",
    "valencia": "Valencia", "villarreal": "Villarreal", "sevilla": "Sevilla", "getafe": "Getafe",
    # Serie A
    "ac milan": "AC Milan", "milan": "AC Milan", "inter milan": "Inter Milan", "inter": "Inter Milan",
    "juventus": "Juventus", "juve": "Juventus", "napoli": "Napoli", "roma": "Roma", "lazio": "Lazio",
    "atalanta": "Atalanta", "fiorentina": "Fiorentina", "torino": "Torino", "bologna": "Bologna",
    # Ligue 1
    "psg": "Paris Saint-Germain", "paris saint-germain": "Paris Saint-Germain", "marseille": "Marseille",
    "olympique marseille": "Marseille", "lyon": "Lyon", "monaco": "Monaco", "nice": "Nice", "lille": "Lille",
    "rennes": "Rennes", "lens": "Lens", "strasbourg": "Strasbourg", "angers": "Angers", "brest": "Brest",
    # Các đội tuyển quốc gia
    "germany": "Germany", "france": "France", "england": "England", "spain": "Spain", "italy": "Italy",
    "portugal": "Portugal", "netherlands": "Netherlands", "belgium": "Belgium", "argentina": "Argentina",
    "brazil": "Brazil", "japan": "Japan", "south korea": "South Korea", "usa": "United States",
}

def normalize_team_name(name: str) -> str:
    if not name:
        return name
    name_lower = name.lower().strip()
    name_lower = re.sub(r'\b(fc|sc|as|us|ac|ssc|sv|tsv|vfl)\b', '', name_lower)
    name_lower = re.sub(r'[^\w\s]', '', name_lower)
    name_lower = name_lower.strip()
    best_match = name
    best_match_key = None
    for key, canonical in TEAM_NAME_MAPPING.items():
        if key in name_lower:
            if best_match_key is None or len(key) > len(best_match_key):
                best_match_key = key
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
    else:
        return matchup
    if not away or not home:
        return matchup
    away_norm = normalize_team_name(away)
    home_norm = normalize_team_name(home)
    return (away_norm, home_norm)

# ==================== LỌC GIAO HỮU ====================
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

# ==================== LỌC GIẢI CÚP ====================
def has_premier_league_team(matchup: str, premier_league_teams: set) -> bool:
    """Kiểm tra matchup có chứa ít nhất một đội Premier League hay không"""
    if not premier_league_teams:
        return True
    matchup_lower = matchup.lower()
    for team in premier_league_teams:
        if team.lower() in matchup_lower:
            return True
    return False

# ==================== CẤU HÌNH GIẢI (livesportsontv) ====================
LEAGUES_CONFIG = {
    "Premier League": {
        "url": "https://www.livesportsontv.com/league/premier-league",
        "teams": {"arsenal", "aston villa", "bournemouth", "brentford", "brighton",
                  "chelsea", "crystal palace", "everton", "fulham", "leeds united",
                  "liverpool", "manchester city", "manchester united", "newcastle",
                  "nottingham forest", "sunderland", "tottenham", "west ham", "wolverhampton"}
    },
    "Serie A": {
        "url": "https://www.livesportsontv.com/league/serie-a",
        "teams": {"inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"}
    },
    "La Liga": {
        "url": "https://www.livesportsontv.com/league/la-liga",
        "teams": {"barcelona", "real madrid", "atlético"}
    },
    "Bundesliga": {
        "url": "https://www.livesportsontv.com/league/bundesliga-5",
        "teams": {"bayern", "borussia dortmund", "bayer leverkusen"}
    },
    "Ligue 1": {
        "url": "https://www.livesportsontv.com/league/ligue-1-3",
        "teams": {"psg", "marseille"}
    },
    "UEFA Champions League": {
        "url": "https://www.livesportsontv.com/league/uefa-champions-league",
        "teams": None
    },
    "UEFA Europa League": {
        "url": "https://www.livesportsontv.com/league/uefa-europa-league",
        "teams": None
    },
    "UEFA Europa Conference League": {
        "url": "https://www.livesportsontv.com/league/uefa-conference-league",
        "teams": None
    },
    "UEFA European Championship": {
        "url": "https://www.livesportsontv.com/league/uefa-european-championship",
        "teams": None
    },
    "FIFA World Cup": {
        "url": "https://www.livesportsontv.com/league/fifa-world-cup",
        "teams": None
    },
    "International Friendlies": {
        "url": "https://www.livesportsontv.com/league/friendly",
        "teams": None,
        "custom_filter": include_friendly_match
    },
    "FA Cup": {
        "url": "https://www.livesportsontv.com/league/fa-cup",
        "teams": None,
        "custom_filter": "premier_league_only"
    },
    "Carabao Cup": {
        "url": "https://www.livesportsontv.com/league/carabao-cup",
        "teams": None,
        "custom_filter": "premier_league_only"
    },
    "Tennis (ATP)": {
        "url": "https://www.livesportsontv.com/league/atp",
        "teams": None,
        "is_tennis": True
    },
    "Tennis (WTA)": {
        "url": "https://www.livesportsontv.com/league/wta",
        "teams": None,
        "is_tennis": True
    },
    "Australian Open": {
        "url": "https://www.livesportsontv.com/league/australian-open",
        "teams": None,
        "is_tennis": True
    },
    "French Open": {
        "url": "https://www.livesportsontv.com/league/french-open",
        "teams": None,
        "is_tennis": True
    },
    "Wimbledon": {
        "url": "https://www.livesportsontv.com/league/wimbledon",
        "teams": None,
        "is_tennis": True
    },
    "US Open": {
        "url": "https://www.livesportsontv.com/league/us-open",
        "teams": None,
        "is_tennis": True
    }
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
    all_games = []
    current_year = ref_time.year

    async with async_playwright() as p:
        print("🚀 Khởi động trình duyệt...")
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        page.set_default_navigation_timeout(120000)
        page.set_default_timeout(60000)

        # Lấy danh sách đội Premier League để lọc
        premier_league_teams = set()
        if "Premier League" in LEAGUES_CONFIG and LEAGUES_CONFIG["Premier League"].get("teams"):
            premier_league_teams = LEAGUES_CONFIG["Premier League"]["teams"]

        for league_name, cfg in LEAGUES_CONFIG.items():
            url = cfg["url"]
            team_filter = cfg.get("teams")
            custom_filter = cfg.get("custom_filter")
            is_tennis = cfg.get("is_tennis", False)
            print(f"\n--- {league_name} ---")
            print(f"    URL: {url}")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=120000)
            except Exception as e:
                print(f"    ❌ Lỗi: {e}")
                continue

            for _ in range(4):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            page_tz = extract_timezone_from_html(soup)
            print(f"    🕒 Múi giờ: {page_tz}")

            rows = soup.find_all('div', class_='event--wrapp')
            print(f"    📊 {len(rows)} sự kiện")

            added = 0
            for row in rows:
                try:
                    date_div = row.find('div', class_='event__info--date')
                    if not date_div: continue
                    date_text = date_div.get_text(separator=' ').strip()
                    day_str, month_str = parse_date_from_text(date_text)
                    if not day_str or not month_str:
                        day_tag = date_div.find('b')
                        month_tag = date_div.find('span')
                        if day_tag and month_tag:
                            day_str = day_tag.get_text(strip=True)
                            month_str = month_tag.get_text(strip=True).lower()
                    if not day_str or not month_str: continue

                    month_num = get_month_number(month_str)
                    day_num = int(day_str)

                    time_tag = row.find('time')
                    if not time_tag: continue
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

                    if is_tennis:
                        home_elem = row.find('div', class_=lambda c: c and 'event_participant--home' in c)
                        if not home_elem:
                            home_elem = row.find('div', class_='event__participant--home')
                        if home_elem:
                            matchup = home_elem.get_text(strip=True)
                        else:
                            title_elem = row.find('a', class_='event__title')
                            matchup = title_elem.get_text(strip=True) if title_elem else "Tennis Match"
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

                    # Áp dụng bộ lọc
                    if team_filter is not None:
                        if not any(t.lower() in matchup.lower() for t in team_filter):
                            continue
                    if custom_filter == "premier_league_only":
                        if not has_premier_league_team(matchup, premier_league_teams):
                            continue
                    elif custom_filter is not None and not is_tennis:
                        if home_elem and away_elem:
                            if not custom_filter(home, away):
                                continue
                        else:
                            continue

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

                    all_games.append({
                        "Date": vn_dt.strftime("%Y-%m-%d"),
                        "Time": vn_dt.strftime("%H:%M"),
                        "League": league_name,
                        "Matchup": matchup,
                        "Services": channels
                    })
                    added += 1
                except:
                    continue
            print(f"    ✅ Thêm {added} trận")
        await browser.close()
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
