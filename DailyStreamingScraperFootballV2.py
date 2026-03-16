# File: DailyStreamingScraperFootballV2_Fixed2.py
# Mô tả: ĐÃ SỬA LỖI TypeError NoneType await + timeout
# - Xóa "await" ở set_default_navigation_timeout và set_default_timeout (đây là hàm SYNC)
# - Giữ nguyên tất cả fix timeout + retry + GitHub Actions ổn định
# - Chạy mượt trên ubuntu-latest (GitHub)

import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import json
from datetime import datetime

async def scrape_league_schedules():
    # ====================== CẤU HÌNH GIẢI ĐẤU ======================
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
        "Tennis (ATP)": {
            "url": "https://www.livesportsontv.com/league/atp",
            "teams": None
        }
    }

    all_games = []
    today = datetime.now()
    target_day = str(today.day)
    target_month = today.strftime("%b").lower()

    async with async_playwright() as p:
        print("🚀 Khởi động browser headless (GitHub Actions)...")
        
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        page = await browser.new_page()
        
        # === SỬA LỖI TypeError Ở ĐÂY ===
        # Không dùng await vì đây là hàm SYNC
        page.set_default_navigation_timeout(120000)  # 120 giây
        page.set_default_timeout(60000)

        for league_name, config in leagues_config.items():
            url = config["url"]
            team_filter = config.get("teams")
            print(f"\n--- Scraping {league_name}: {url} ---")

            # Retry 2 lần nếu timeout
            for attempt in range(2):
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=120000)
                    break
                except Exception as e:
                    print(f"   ⚠️ Lần {attempt+1} timeout, thử lại...")
                    if attempt == 1:
                        print(f"   ❌ Bỏ qua {league_name}")
                        continue

            # Scroll load dữ liệu
            for _ in range(4):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

            html_content = await page.content()
            soup = BeautifulSoup(html_content, 'html.parser')

            game_rows = soup.find_all('div', class_='event--wrapp')
            print(f"  → Tìm thấy {len(game_rows)} trận. Lọc ngày hôm nay...")

            games_added = 0

            for row in game_rows:
                try:
                    date_div = row.find('div', class_='event__info--date')
                    if not date_div: continue
                    
                    game_day = date_div.find('b').get_text(strip=True) if date_div.find('b') else ""
                    game_month = date_div.find('span').get_text(strip=True).lower() if date_div.find('span') else ""

                    if game_day != target_day or game_month != target_month:
                        continue

                    time_div = row.find('time')
                    event_time = time_div.get_text(strip=True) if time_div else "Time Not Found"

                    home_elem = row.find('div', class_=lambda c: c and 'event__participant--home' in c)
                    away_elem = row.find('div', class_=lambda c: c and 'event__participant--away' in c)
                    
                    home_team = home_elem.get_text(strip=True) if home_elem else "Unknown"
                    away_team = away_elem.get_text(strip=True) if away_elem else "Unknown"
                    matchup = f"{away_team} @ {home_team}"

                    if team_filter is not None:
                        if not any(t.lower() in home_team.lower() or t.lower() in away_team.lower() for t in team_filter):
                            continue

                    channels = []
                    channel_list = row.find('ul', class_='event__tags')
                    if channel_list:
                        for link in channel_list.find_all('a'):
                            if aria := link.get('aria-label'):
                                channels.append(aria.strip())

                    all_games.append({
                        "Date": today.strftime("%Y-%m-%d"),
                        "Time": event_time,
                        "League": league_name,
                        "Matchup": matchup,
                        "Services": channels
                    })
                    games_added += 1

                except:
                    continue

            print(f"  → Đã thêm {games_added} trận {league_name}")

        await browser.close()
        print("\n✅ Hoàn tất scrape!")

    # ====================== XUẤT JSON ======================
    filename = "schedule_livesportsontv.json"
    if all_games:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(all_games, f, indent=4, ensure_ascii=False)
        
        print(f"\n🎉 THÀNH CÔNG: {len(all_games)} trận!")
        print(f"📁 File: {filename} (sẵn sàng commit)")
    else:
        print("⚠️ Không có trận nào hôm nay.")

if __name__ == "__main__":
    asyncio.run(scrape_league_schedules())
