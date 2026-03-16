import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

async def scrape_wheresthematch():
    # Danh sách đội bóng yêu cầu (Cập nhật đầy đủ các biến thể)
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
    today_day_num = str(int(datetime.now().strftime("%d"))) # Ngày hiện tại (ví dụ: 16)

    async with async_playwright() as p:
        print("🚀 Đang khởi động trình duyệt (Bản V7 - Fix Selector chuẩn)...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36")
        page = await context.new_page()
        
        url = "https://www.wheresthematch.com/live-football-on-tv/"
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            # Cuộn trang từ từ để kích hoạt lazy load cho logo kênh
            for i in range(5):
                await page.mouse.wheel(0, 800)
                await asyncio.sleep(0.5)
            
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
        except Exception as e:
            print(f"❌ Lỗi tải trang: {e}")
            await browser.close()
            return

        await browser.close()

        # 1. Tìm các cụm ngày
        groups = soup.select('.fixtures-group')
        for group in groups:
            # Kiểm tra xem group này có phải hôm nay/tối nay không
            date_header = group.select_one('.fixture-date')
            date_text = date_header.get_text(strip=True).lower() if date_header else ""
            
            if not any(x in date_text for x in ["today", "tonight", today_day_num]):
                continue
            
            # 2. Duyệt từng trận trong ngày hôm nay
            fixture_items = group.select('.fixture-item')
            for item in fixture_items:
                try:
                    # Lấy giải đấu (Thường nằm ở class competition-name)
                    comp_tag = item.select_one('.competition-name')
                    league_raw = comp_tag.get_text(strip=True) if comp_tag else "Unknown League"
                    
                    # Lấy tên đội chính xác từ class
                    home_tag = item.select_one('.team-home')
                    away_tag = item.select_one('.team-away')
                    
                    if not home_tag or not away_tag:
                        # Fallback nếu cấu trúc cũ hơn
                        teams = item.select('.team-name')
                        if len(teams) >= 2:
                            home_name = teams[0].get_text(strip=True)
                            away_name = teams[1].get_text(strip=True)
                        else: continue
                    else:
                        home_name = home_tag.get_text(strip=True)
                        away_name = away_tag.get_text(strip=True)

                    matchup = f"{home_name} vs {away_name}"
                    
                    # Lấy giờ thi đấu
                    time_tag = item.select_one('.kick-off-time')
                    kickoff = time_tag.get_text(strip=True) if time_tag else "Tonight"

                    # Lấy Kênh truyền hình
                    channels = []
                    # Ưu tiên lấy từ các thẻ hình ảnh trong class broadcaster-logos
                    broadcasters = item.select('.broadcaster-logos img')
                    for b in broadcasters:
                        c_name = b.get('alt', '').replace(' logo', '').strip()
                        if c_name and c_name not in channels:
                            channels.append(c_name)
                    
                    # Nếu không có ảnh, lấy từ text broadcaster-name
                    if not channels:
                        b_names = item.select('.broadcaster-name')
                        for bn in b_names:
                            channels.append(bn.get_text(strip=True))

                    # 3. Lọc trận đấu
                    is_match_interested = False
                    matched_league = league_raw
                    
                    for lg_key, cfg in leagues_config.items():
                        team_list = cfg.get("teams")
                        # Nếu là giải Cup (None) hoặc đội bóng nằm trong list yêu cầu
                        if team_list is None:
                            if lg_key.lower() in league_raw.lower():
                                is_match_interested = True
                                matched_league = lg_key
                                break
                        else:
                            if any(t in home_name.lower() or t in away_name.lower() for t in team_list):
                                is_match_interested = True
                                matched_league = lg_key
                                break
                    
                    if is_match_interested:
                        all_games.append({
                            "Date": datetime.now().strftime("%Y-%m-%d"),
                            "Time": kickoff,
                            "League": matched_league,
                            "Matchup": matchup,
                            "Channels": list(dict.fromkeys(channels))
                        })

                except Exception:
                    continue

    # Xuất kết quả
    if all_games:
        with open("wheresthematch.json", 'w', encoding='utf-8') as f:
            json.dump(all_games, f, indent=4, ensure_ascii=False)
        print(f"✅ THÀNH CÔNG: Tìm thấy {len(all_games)} trận đúng yêu cầu.")
        for g in all_games:
            print(f"  ⚽ {g['Time']} | {g['Matchup']} | Kênh: {', '.join(g['Channels'])}")
    else:
        print("⚠️ Không tìm thấy trận nào khớp yêu cầu. Kiểm tra lại danh sách đội hoặc ngày thi đấu.")

if __name__ == "__main__":
    asyncio.run(scrape_wheresthematch())
