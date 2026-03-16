import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

async def scrape_wheresthematch():
    # Cấu hình danh sách đội và giải đấu cần lấy
    leagues_config = {
        "Premier League": {"teams": {"arsenal", "aston villa", "bournemouth", "brentford", "brighton",
                                     "chelsea", "crystal palace", "everton", "fulham", "liverpool", 
                                     "manchester city", "manchester united", "newcastle",
                                     "nottingham forest", "tottenham hotspur", "west ham united", 
                                     "wolverhampton", "wolves", "leicester city", "ipswich town", "southampton"}},
        "Serie A": {"teams": {"inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"}},
        "La Liga": {"teams": {"barcelona", "real madrid", "atletico"}},
        "Bundesliga": {"teams": {"bayern", "borussia dortmund", "bayer leverkusen"}},
        "Ligue 1": {"teams": {"psg", "marseille"}},
        "UEFA Champions League": {"teams": None},
        "UEFA Europa League": {"teams": None},
        "Tennis (ATP)": {"teams": None}
    }

    all_games = []
    today_day = datetime.now().strftime("%d") # Lấy ngày hiện tại để đối chiếu

    async with async_playwright() as p:
        print("🚀 Khởi động trình duyệt...")
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        url = "https://www.wheresthematch.com/live-football-on-tv/"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            # Cuộn trang nhẹ để kích hoạt load ảnh logo kênh
            await page.mouse.wheel(0, 2000)
            await asyncio.sleep(2)
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
        except Exception as e:
            print(f"❌ Lỗi: {e}")
            await browser.close()
            return

        await browser.close()

        # Tìm các nhóm ngày (fixtures-group)
        fixture_groups = soup.select('.fixtures-group')
        
        for group in fixture_groups:
            # Kiểm tra tiêu đề ngày
            date_header = group.select_one('.fixture-date')
            date_text = date_header.get_text(strip=True).lower() if date_header else ""
            
            # Chỉ xử lý nếu là "Today", "Tonight" hoặc khớp ngày hiện tại
            if not any(x in date_text for x in ["today", "tonight", today_day]):
                continue

            # Duyệt từng trận đấu trong nhóm ngày này
            matches = group.select('.fixture-item') 
            for match_card in matches:
                try:
                    # 1. Lấy tên đội (Dùng selector chính xác của web)
                    teams = match_card.select('.team-name')
                    if len(teams) < 2: continue
                    
                    home = teams[0].get_text(strip=True)
                    away = teams[1].get_text(strip=True)
                    matchup = f"{home} vs {away}"

                    # 2. Lấy giờ và Giải đấu
                    kickoff = match_card.select_one('.kick-off-time').get_text(strip=True) if match_card.select_one('.kick-off-time') else "Tonight"
                    league_name = match_card.select_one('.competition-name').get_text(strip=True) if match_card.select_one('.competition-name') else "Unknown"

                    # 3. Lấy danh sách kênh phát sóng
                    channels = []
                    # Ưu tiên lấy từ alt của ảnh logo kênh
                    for img in match_card.select('.broadcaster-logos img'):
                        ch_name = img.get('alt', '').replace(' logo', '').strip()
                        if ch_name and ch_name not in channels:
                            channels.append(ch_name)

                    # 4. Kiểm tra bộ lọc đội bóng/giải đấu
                    is_match_interested = False
                    for lg, cfg in leagues_config.items():
                        team_list = cfg.get("teams")
                        # Nếu là giải Cup (None) hoặc đội bóng nằm trong list yêu cầu
                        if team_list is None:
                            if lg.lower() in league_name.lower():
                                is_match_interested = True
                                break
                        elif any(t in home.lower() or t in away.lower() for t in team_list):
                            is_match_interested = True
                            break

                    if is_match_interested:
                        all_games.append({
                            "Date": datetime.now().strftime("%Y-%m-%d"),
                            "Time": kickoff,
                            "League": league_name,
                            "Matchup": matchup,
                            "Channels": list(dict.fromkeys(channels))
                        })

                except:
                    continue

    # Xuất kết quả ra file
    if all_games:
        with open("wheresthematch.json", 'w', encoding='utf-8') as f:
            json.dump(all_games, f, indent=4, ensure_ascii=False)
        print(f"✅ Đã lưu {len(all_games)} trận vào wheresthematch.json")
    else:
        print("⚠️ Không tìm thấy trận đấu nào khớp yêu cầu hôm nay.")

if __name__ == "__main__":
    # Đã sửa lỗi SyntaxError tại đây
    asyncio.run(scrape_wheresthematch())
