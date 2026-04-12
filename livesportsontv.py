# File: livesportsontv.py
# Tích hợp nhiều nguồn footonsat, sửa lỗi timezone, lọc thời gian linh hoạt (2h trước, 26h sau)

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

# Danh sách các nguồn footonsat
FOOTONSAT_URLS = [
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/premierleague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/seriea.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/laliga.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/bundesliga.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/ligue1.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/championsleague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/europaleague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/ConferenceLeague.json"
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

# ==================== LỌC GIAO HỮU ====================
EUROPEAN_COUNTRIES = {
    "albania", "andorra", "armenia", "austria", "azerbaijan", "belarus", "belgium",
    "bosnia", "bulgaria", "croatia", "cyprus", "czech", "denmark", "england",
    "estonia", "faroe", "finland", "france", "georgia", "germany", "gibraltar",
    "greece", "hungary", "iceland", "israel", "italy", "kazakhstan", "kosovo",
    "latvia", "liechtenstein", "lithuania", "luxembourg", "malta", "moldova",
    "monaco", "montenegro", "netherlands", "north macedonia", "northern ireland",
    "norway", "poland", "portugal", "republic of ireland", "romania", "russia",
    "san marino", "scotland", "serbia", "slovakia", "slovenia", "spain", "sweden",
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
                        league = current_match['compet'].strip()
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
                league = current_match['compet'].strip()
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

                    if team_filter is not None:
                        if not any(t.lower() in matchup.lower() for t in team_filter):
                            continue
                    if custom_filter is not None and not is_tennis:
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

    all_games = games_live + games_foot
    unique = {}
    for g in all_games:
        key = (g["Date"], g["Time"], g["League"], g["Matchup"])
        if key not in unique or len(g["Services"]) > len(unique[key]["Services"]):
            unique[key] = g

    final = list(unique.values())
    final.sort(key=lambda x: (x["Date"], x["Time"]))

    with open("schedule_livesportsontv.json", "w", encoding="utf-8") as f:
        json.dump(final, f, indent=4, ensure_ascii=False)

    print(f"\n🎉 TỔNG KẾT: {len(final)} trận (đã gộp và loại trùng)")

if __name__ == "__main__":
    asyncio.run(main())
