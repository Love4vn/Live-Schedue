# File: livesportsontv.py
# Hoàn chỉnh - Lấy lịch bóng đá & tennis, giờ Việt Nam, xử lý linh hoạt ngày tháng

import asyncio
import json
import re
from datetime import datetime
import zoneinfo
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# ==================== CẤU HÌNH MÚI GIỜ ====================
UK_TZ = zoneinfo.ZoneInfo("Europe/London")
VIETNAM_TZ = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")

# Ánh xạ tháng (hỗ trợ tiếng Anh và tiếng Việt)
MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "tháng 1": 1, "tháng 2": 2, "tháng 3": 3, "tháng 4": 4, "tháng 5": 5,
    "tháng 6": 6, "tháng 7": 7, "tháng 8": 8, "tháng 9": 9, "tháng 10": 10,
    "tháng 11": 11, "tháng 12": 12
}

# ==================== HÀM TIỆN ÍCH ====================
def parse_date_from_text(text):
    """Trích xuất ngày và tháng từ chuỗi như '03 Mar' hoặc '03 THÁNG 4'"""
    text = text.strip().lower()
    # Tìm số ngày và phần tháng
    match = re.search(r'(\d{1,2})\s+([a-zà-ỹ0-9\s]+)', text)
    if match:
        day = match.group(1)
        month_str = match.group(2).strip()
        return day, month_str
    return None, None

def parse_time_with_ampm(time_str: str):
    """Chuyển '10:00 PM' sang 24h (22, 00)"""
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
    minute = int(hour_min[1])
    if meridiem == 'PM' and hour != 12:
        hour += 12
    elif meridiem == 'AM' and hour == 12:
        hour = 0
    return hour, minute

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

# ==================== CẤU HÌNH GIẢI ĐẤU ====================
LEAGUES_CONFIG = {
    # Bóng đá câu lạc bộ
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
    # Đội tuyển quốc gia
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
    # Tennis
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

# ==================== HÀM CHÍNH ====================
async def scrape_league_schedules():
    all_games = []
    now_uk = datetime.now(UK_TZ)
    target_day = str(now_uk.day)
    target_month_abbr = now_uk.strftime("%b").lower()
    current_year = now_uk.year

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
            print(f"\n--- Đang xử lý: {league_name} ---")
            print(f"    URL: {url}")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=120000)
            except Exception as e:
                print(f"    ❌ Lỗi tải trang: {e}")
                continue

            # Cuộn để tải hết nội dung
            for _ in range(4):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            rows = soup.find_all('div', class_='event--wrapp')
            print(f"    📊 Tìm thấy {len(rows)} sự kiện.")

            added = 0
            for row in rows:
                try:
                    # ---- Lấy ngày tháng ----
                    date_div = row.find('div', class_='event__info--date')
                    if not date_div:
                        continue
                    # Thử lấy text tổng hợp
                    date_text = date_div.get_text(separator=' ').strip()
                    if date_text:
                        day_str, month_str = parse_date_from_text(date_text)
                    # Nếu không parse được, dùng b và span
                    if not day_str or not month_str:
                        day_tag = date_div.find('b')
                        month_tag = date_div.find('span')
                        if day_tag and month_tag:
                            day_str = day_tag.get_text(strip=True)
                            month_str = month_tag.get_text(strip=True).lower()
                    if not day_str or not month_str:
                        continue

                    # Chuyển tháng thành số và so sánh với ngày UK
                    month_num = None
                    for k, v in MONTH_MAP.items():
                        if k in month_str:
                            month_num = v
                            break
                    if month_num is None:
                        continue
                    # Lấy tên tháng viết tắt tiếng Anh từ số
                    month_abbr = datetime(current_year, month_num, 1).strftime("%b").lower()
                    if day_str != target_day or month_abbr != target_month_abbr:
                        continue

                    # ---- Lấy giờ ----
                    time_tag = row.find('time')
                    if not time_tag:
                        continue
                    time_str = time_tag.get_text(strip=True)
                    try:
                        hour, minute = parse_time_with_ampm(time_str)
                    except:
                        continue

                    # Tạo datetime UK và chuyển sang VN
                    uk_dt = datetime(current_year, month_num, int(day_str), hour, minute)
                    uk_dt = uk_dt.replace(tzinfo=UK_TZ)
                    vn_dt = uk_dt.astimezone(VIETNAM_TZ)

                    # ---- Tên trận đấu / giải đấu ----
                    if is_tennis:
                        # Tennis: lấy từ div event_participant--home hoặc event__title
                        home_elem = row.find('div', class_=lambda c: c and 'event_participant--home' in c)
                        if not home_elem:
                            home_elem = row.find('div', class_='event__participant--home')
                        if home_elem:
                            matchup = home_elem.get_text(strip=True)
                        else:
                            title_elem = row.find('a', class_='event__title')
                            matchup = title_elem.get_text(strip=True) if title_elem else "Tennis Match"
                    else:
                        # Bóng đá: home/away
                        home_elem = row.find('div', class_=lambda c: c and 'event__participant--home' in c)
                        away_elem = row.find('div', class_=lambda c: c and 'event__participant--away' in c)
                        home = home_elem.get_text(strip=True) if home_elem else "?"
                        away = away_elem.get_text(strip=True) if away_elem else "?"
                        matchup = f"{away} @ {home}"
                        if home == "?" and away == "?":
                            title_elem = row.find('a', class_='event__title')
                            if title_elem:
                                matchup = title_elem.get_text(strip=True)

                    # Áp dụng bộ lọc đội bóng (nếu có)
                    if team_filter is not None:
                        if not any(t.lower() in matchup.lower() for t in team_filter):
                            continue
                    if custom_filter is not None and not is_tennis:
                        if home_elem and away_elem:
                            if not custom_filter(home, away):
                                continue
                        else:
                            continue

                    # ---- Kênh phát sóng ----
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

                except Exception as e:
                    # Bỏ qua lỗi nhỏ ở từng dòng
                    continue

            print(f"    ✅ Đã thêm {added} trận")

        await browser.close()

    # Ghi kết quả ra file JSON
    filename = "schedule_livesportsontv.json"
    if all_games:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(all_games, f, indent=4, ensure_ascii=False)
        print(f"\n🎉 THÀNH CÔNG! Đã lấy {len(all_games)} trận.")
        print(f"📁 Lưu tại: {filename}")
    else:
        print("\n⚠️ Không có trận đấu nào hôm nay (theo giờ UK).")

if __name__ == "__main__":
    asyncio.run(scrape_league_schedules())
