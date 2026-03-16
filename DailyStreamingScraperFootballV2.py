# File: DailyStreamingScraperFootballV2.py
# Mô tả: Script Python chạy trên GitHub (hoặc local) dùng Playwright + BeautifulSoup
# để scrape lịch thi đấu bóng đá (Premier League, Serie A, La Liga, Bundesliga, Ligue 1,
# UEFA Champions League, Europa League, Conference League) + Tennis (ATP) từ livesportsontv.com
# Chỉ lấy trận đấu hôm nay và lọc theo danh sách đội bạn cung cấp.
# Kết quả xuất ra file JSON: livesportsontv.json (ghi đè mỗi ngày)

import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import json
from datetime import datetime

async def scrape_league_schedules():
    # ====================== CẤU HÌNH CÁC GIẢI ĐẤU ======================
    leagues_config = {
        "Premier League": {
            "url": "https://www.livesportsontv.com/league/premier-league",
            "teams": {"arsenal", "aston villa", "bournemouth", "brentford", "brighton",
                      "chelsea", "crystal palace", "everton", "fulham", "leeds united",
                      "liverpool", "manchester city", "manchester united", "newcastle",
                      "nottingham forest", "sunderland", "tottenham hotspur",
                      "west ham united", "wolverhampton"}
        },
        "Serie A": {
            "url": "https://www.livesportsontv.com/league/serie-a",
            "teams": {"inter milan", "ac milan", "napoli", "juventus", "roma",
                      "atalanta", "lazio"}
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
            "teams": {"psg", "olympique marseille"}
        },
        "UEFA Champions League": {
            "url": "https://www.livesportsontv.com/league/uefa-champions-league",
            "teams": None  # lấy tất cả
        },
        "UEFA Europa League": {
            "url": "https://www.livesportsontv.com/league/uefa-europa-league",
            "teams": None
        },
        "UEFA Europa Conference League": {
            "url": "https://www.livesportsontv.com/league/uefa-conference-league",
            "teams": None
        },
        "Tennis (ATP)": {
            "url": "https://www.livesportsontv.com/league/atp",
            "teams": None  # tennis chung - lấy tất cả
        }
    }

    all_games = []
    today = datetime.now()
    target_day = str(today.day)
    target_month = today.strftime("%b").lower()

    async with async_playwright() as p:
        print("🚀 Đang khởi động browser headless...")
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for league_name, config in leagues_config.items():
            url = config["url"]
            team_filter = config.get("teams")
            print(f"\n--- Scraping {league_name}: {url} ---")

            await page.goto(url, wait_until="networkidle")
            
            # Scroll để load hết trận (đặc biệt ngày nhiều trận)
            for _ in range(4):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1200)

            html_content = await page.content()
            soup = BeautifulSoup(html_content, 'html.parser')

            game_rows = soup.find_all('div', class_='event--wrapp')
            print(f"  → Tìm thấy {len(game_rows)} trận. Lọc ngày hôm nay ({target_day} {target_month})...")

            games_added = 0

            for row in game_rows:
                try:
                    # Lấy ngày
                    date_div = row.find('div', class_='event__info--date')
                    if not date_div:
                        continue
                    game_day = date_div.find('b').get_text(strip=True) if date_div.find('b') else ""
                    game_month = date_div.find('span').get_text(strip=True).lower() if date_div.find('span') else ""

                    if game_day != target_day or game_month != target_month:
                        continue

                    # Thời gian
                    time_div = row.find('time')
                    event_time = time_div.get_text(strip=True) if time_div else "Time Not Found"

                    # Đội bóng
                    home_elem = row.find('div', class_=lambda c: c and 'event__participant--home' in c)
                    away_elem = row.find('div', class_=lambda c: c and 'event__participant--away' in c)
                    
                    home_team = home_elem.get_text(strip=True) if home_elem else "Unknown Home"
                    away_team = away_elem.get_text(strip=True) if away_elem else "Unknown Away"
                    matchup = f"{away_team} @ {home_team}"

                    # Lọc theo danh sách đội (nếu có)
                    if team_filter is not None:
                        home_lower = home_team.lower()
                        away_lower = away_team.lower()
                        match_found = any(t.lower() in home_lower or t.lower() in away_lower for t in team_filter)
                        if not match_found:
                            continue

                    # Kênh phát sóng
                    channels = []
                    channel_list = row.find('ul', class_='event__tags')
                    if channel_list:
                        for link in channel_list.find_all('a'):
                            aria = link.get('aria-label')
                            if aria:
                                channels.append(aria.strip())

                    all_games.append({
                        "Date": today.strftime("%Y-%m-%d"),
                        "Time": event_time,
                        "League": league_name,
                        "Matchup": matchup,
                        "Services": channels
                    })
                    games_added += 1

                except Exception as e:
                    # print(f"    Lỗi parse trận {league_name}: {e}")
                    continue

            print(f"  → Đã thêm {games_added} trận {league_name} hôm nay.")

        await browser.close()
        print("\n✅ Hoàn tất scrape tất cả giải đấu.")

    # ====================== XUẤT FILE JSON ======================
    filename = "livesportsontv.json"
    
    if all_games:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(all_games, f, indent=4, ensure_ascii=False)
        
        print(f"\n🎉 ĐÃ LẤY THÀNH CÔNG {len(all_games)} TRẬN ĐẤU!")
        print(f"📁 File JSON được lưu: {filename}")
        print("   (Bạn có thể push file này lên GitHub repo để dùng tiếp)")
    else:
        print("⚠️ Không tìm thấy trận nào hôm nay.")

if __name__ == "__main__":
    asyncio.run(scrape_league_schedules())
