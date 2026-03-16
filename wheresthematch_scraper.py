import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

async def scrape_wheresthematch():
    # Danh sách cấu hình giải đấu và đội bóng
    leagues_config = {
        "Premier League": {"teams": {
            "arsenal", "aston villa", "bournemouth", "brentford", "brighton",
            "chelsea", "crystal palace", "everton", "fulham", "liverpool", 
            "manchester city", "man city", "manchester united", "man utd", "newcastle",
            "nottingham forest", "tottenham", "spurs", "west ham", 
            "wolverhampton", "wolves", "leicester", "ipswich", "southampton"
        }},
        "Serie A": {"teams": {"inter", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"}},
        "La Liga": {"teams": {"barcelona", "real madrid", "atletico"}},
        "Bundesliga": {"teams": {"bayern", "borussia", "dortmund", "bayer leverkusen", "leverkusen"}},
        "Ligue 1": {"teams": {"psg", "marseille"}},
        "UEFA Champions League": {"teams": None},
        "UEFA Europa League": {"teams": None},
        "Tennis (ATP)": {"teams": None}
    }

    all_games = []
    today_day = str(int(datetime.now().strftime("%d"))) # Ví dụ: "16"

    async with async_playwright() as p:
        print("🚀 Khởi động trình duyệt (Bản V8: Deep DOM Scraper)...")
        browser = await p.chromium.launch(headless=True)
        # Sử dụng User-Agent thật để tránh bị block
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
        page = await context.new_page()
        
        url = "https://www.wheresthematch.com/live-football-on-tv/"
        try:
            # Chờ trang tải hoàn tất các script
            await page.goto(url, wait_until="networkidle", timeout=60000)
            # Cuộn trang từ từ để load các logo đài truyền hình (Lazy Loading)
            for _ in range(3):
                await page.mouse.wheel(0, 1000)
                await asyncio.sleep(1)
            
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
        except Exception as e:
            print(f"❌ Lỗi khi tải trang: {e}")
            await browser.close()
            return

        await browser.close()

        # Tìm các nhóm trận đấu theo ngày
        fixture_groups = soup.select('.fixtures-group')
        
        for group in fixture_groups:
            # Kiểm tra tiêu đề ngày (Ví dụ: "Monday 16th March 2026")
            date_header = group.select_one('.fixture-date-wrapper')
            date_text = date_header.get_text(strip=True).lower() if date_header else ""
            
            # Chỉ lấy các trận của "Today", "Tonight" hoặc đúng ngày hiện tại
            if not any(keyword in date_text for keyword in ["today", "tonight", today_day]):
                continue

            # Duyệt qua từng trận đấu trong group này
            matches = group.select('.fixture-item')
            for match_item in matches:
                try:
                    # 1. Lấy tên Đội bóng (Dùng class chính xác)
                    home_team = match_item.select_one('.team-home').get_text(strip=True)
                    away_team = match_item.select_one('.team-away').get_text(strip=True)
                    matchup = f"{home_team} vs {away_team}"
                    
                    # 2. Lấy giờ thi đấu
                    time_tag = match_item.select_one('.kick-off-time')
                    match_time = time_tag.get_text(strip=True) if time_tag else "Tonight"
                    
                    # 3. Lấy Giải đấu
                    league_tag = match_item.select_one('.competition-name')
                    league_name = league_tag.get_text(strip=True) if league_tag else "Unknown League"

                    # 4. Lấy Kênh truyền hình (Bóc tách từ Logo hoặc Text)
                    channels = []
                    # Tìm trong danh sách logo
                    broadcaster_images = match_item.select('.broadcaster-logos img')
                    for img in broadcaster_images:
                        alt_text = img.get('alt', '').replace(' logo', '').strip()
                        if alt_text and alt_text not in channels:
                            channels.append(alt_text)
                    
                    # Nếu không thấy logo, tìm trong text (broadcaster-name)
                    if not channels:
                        b_names = match_item.select('.broadcaster-name')
                        for b in b_names:
                            channels.append(b.get_text(strip=True))

                    # 5. Bộ lọc: Kiểm tra giải đấu hoặc đội bóng có nằm trong list quan tâm không
                    is_interested = False
                    final_league_key = league_name

                    for lg_key, cfg in leagues_config.items():
                        team_list = cfg.get("teams")
                        # Nếu là giải Cup hoặc giải quan tâm
                        if lg_key.lower() in league_name.lower():
                            if team_list is None: # Giải Cup lấy hết
                                is_interested = True
                                final_league_key = lg_key
                                break
                            else: # Giải League check tên đội
                                if any(t in home_team.lower() or t in away_team.lower() for t in team_list):
                                    is_interested = True
                                    final_league_key = lg_key
                                    break
                    
                    if is_interested:
                        all_games.append({
                            "Date": datetime.now().strftime("%Y-%m-%d"),
                            "Time": match_time,
                            "League": final_league_key,
                            "Matchup": matchup,
                            "Channels": channels
                        })

                except Exception:
                    continue

    # Xuất kết quả
    if all_games:
        with open("wheresthematch.json", 'w', encoding='utf-8') as f:
            json.dump(all_games, f, indent=4, ensure_ascii=False)
        print(f"✅ THÀNH CÔNG: Đã tìm thấy {len(all_games)} trận hôm nay.")
        for g in all_games:
            print(f"  ⚽ {g['Time']} | {g['Matchup']} | Kênh: {', '.join(g['Channels'])}")
    else:
        print("⚠️ Không tìm thấy trận đấu nào khớp yêu cầu. Có thể danh sách đội cần được cập nhật.")

if __name__ == "__main__":
    asyncio.run(scrape_wheresthematch())
