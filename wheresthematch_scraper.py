import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

async def scrape_wheresthematch():
    # Danh sách các đội bóng yêu cầu (Cập nhật đầy đủ hơn)
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
    today_date = datetime.now().strftime("%A %d%s %B %Y") # Định dạng khớp với tiêu đề web

    async with async_playwright() as p:
        print("🚀 Khởi động trình duyệt lấy lịch chuẩn xác...")
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        url = "https://www.wheresthematch.com/live-football-on-tv/"
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            # Chờ thêm một chút để các icon kênh kịp load
            await asyncio.sleep(3)
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
        except Exception as e:
            print(f"❌ Lỗi tải trang: {e}")
            await browser.close()
            return

        await browser.close()

        # 1. Tìm tất cả các cụm ngày (fixtures-group)
        # Trang này chia lịch theo từng block ngày
        fixture_groups = soup.select('.fixtures-group')
        
        for group in fixture_groups:
            # Kiểm tra xem group này có phải của "Today" hoặc "Tonight" không
            date_header = group.select_one('.fixture-date')
            date_text = date_header.get_text(strip=True).lower() if date_header else ""
            
            is_today = any(x in date_text for x in ["today", "tonight", datetime.now().strftime("%d").lower()])
            if not is_today:
                continue

            # 2. Duyệt từng trận trong group ngày hôm nay
            matches = group.select('.fixture-item') # Thẻ chứa thông tin trận đấu
            for match_card in matches:
                try:
                    # Lấy tên đội
                    teams = match_card.select('.team-name')
                    if len(teams) < 2: continue
                    
                    home_team = teams[0].get_text(strip=True)
                    away_team = teams[1].get_text(strip=True)
                    matchup = f"{home_team} vs {away_team}"

                    # Lấy giờ thi đấu
                    time_val = match_card.select_one('.kick-off-time')
                    kickoff = time_val.get_text(strip=True) if time_val else "Unknown"

                    # Lấy giải đấu
                    competition = match_card.select_one('.competition-name')
                    league_name = competition.get_text(strip=True) if competition else "Unknown League"

                    # Lấy danh sách kênh (từ thẻ img và text)
                    channels = []
                    # Cách 1: Từ các icon đài truyền hình
                    channel_imgs = match_card.select('.broadcaster-logos img')
                    for img in channel_imgs:
                        alt = img.get('alt', '').replace(' logo', '').strip()
                        if alt and alt not in channels:
                            channels.append(alt)
                    
                    # Cách 2: Nếu có text đài truyền hình bổ sung
                    channel_texts = match_card.select('.broadcaster-name')
                    for ct in channel_texts:
                        name = ct.get_text(strip=True)
                        if name and name not in channels:
                            channels.append(name)

                    # 3. Lọc theo danh sách đội yêu cầu
                    is_match_interested = False
                    for lg, cfg in leagues_config.items():
                        team_list = cfg.get("teams")
                        # Nếu là giải đấu Cup (teams=None) hoặc đội bóng nằm trong list
                        if team_list is None:
                            if lg.lower() in league_name.lower():
                                is_match_interested = True
                                break
                        elif any(t in home_team.lower() or t in away_team.lower() for t in team_list):
                            is_match_interested = True
                            break

                    if is_match_interested:
                        all_games.append({
                            "Date": datetime.now().strftime("%Y-%m-%d"),
                            "Time": kickoff,
                            "League": league_name,
                            "Matchup": matchup,
                            "Channels": list(dict.fromkeys(channels)) # Loại bỏ trùng
                        })

                except Exception as ex:
                    continue

    # Xuất kết quả
    if all_games:
        with open("wheresthematch.json", 'w', encoding='utf-8') as f:
            json.dump(all_games, f, indent=4, ensure_ascii=False)
        print(f"✅ Thành công: Đã lấy được {len(all_games)} trận đấu hôm nay.")
    else:
        print("⚠️ Không tìm thấy trận đấu nào khớp với yêu cầu hôm nay.")

if __name__ == "__main__":
    async asyncio.run(scrape_wheresthematch())
