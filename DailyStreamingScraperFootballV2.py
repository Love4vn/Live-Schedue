import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

async def scrape_wheresthematch():
    # BỔ SUNG ĐẦY ĐỦ TÊN RÚT GỌN (Wolves, Man City, Man Utd, Spurs...)
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
    today = datetime.now()
    # Lấy ngày hiện tại (ví dụ: "16" thay vì "016")
    today_day = str(int(today.strftime("%d"))) 

    async with async_playwright() as p:
        print("🚀 Khởi động trình duyệt (Bản V6: Quét siêu bám dính DOM)...")
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        url = "https://www.wheresthematch.com/live-football-on-tv/"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.mouse.wheel(0, 2000) # Cuộn trang để load logo đài
            await asyncio.sleep(3)
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
        except Exception as e:
            print(f"❌ Lỗi: {e}")
            await browser.close()
            return

        await browser.close()

        # Quét TẤT CẢ các thẻ có khả năng là 1 dòng chứa trận đấu (div, li, tr)
        potential_cards = []
        for tag in soup.find_all(['li', 'div', 'tr']):
            # Dùng dấu | để tách biệt nội dung các thẻ con bên trong
            text = tag.get_text(separator=" | ", strip=True)
            # Phải chứa chữ ' v ' hoặc ' vs ' và không quá dài (tránh quét nhầm toàn bộ page)
            if (" v " in text.lower() or " vs " in text.lower()) and len(text) < 800:
                potential_cards.append(tag)

        seen_matchups = set()
        
        for card in potential_cards:
            try:
                full_text = card.get_text(separator=" | ", strip=True)
                full_lower = full_text.lower()

                # Bỏ qua bóng đá nữ
                if any(w in full_lower for w in ['women', 'ladies', 'womens']):
                    continue

                # Bắt buộc phải là trận của "Hôm nay" (chứa Tonight, Today, hoặc số ngày hôm nay)
                if "tonight" not in full_lower and "today" not in full_lower and today_day not in full_lower:
                    continue

                # Cắt chuỗi để lấy tên Đội Nhà và Đội Khách
                if " v " in full_lower:
                    parts = full_text.split(" v ", 1)
                else:
                    parts = full_text.split(" vs ", 1)
                
                # parts[0] chứa text trước chữ 'v', phần tử cuối cùng sau dấu '|' là tên đội nhà
                home_team = parts[0].split("|")[-1].strip()
                # parts[1] chứa text sau chữ 'v', phần tử đầu tiên là tên đội khách
                away_team = parts[1].split("|")[0].strip()

                matchup = f"{home_team} vs {away_team}"
                matchup_key = matchup.lower()
                
                # Chống lặp trận (do 1 trận có thể nằm trong nhiều thẻ HTML lồng nhau)
                if matchup_key in seen_matchups:
                    continue

                # Lấy giờ (Regex tìm định dạng HH:MM)
                time_text = "Tonight"
                time_match = re.search(r'(\d{1,2}:\d{2})', full_text)
                if time_match:
                    time_text = time_match.group(1)

                # Lấy Giải Đấu
                league_name = "Unknown League"
                for lg in leagues_config.keys():
                    if lg.lower() in full_lower:
                        league_name = lg
                        break

                # Bộ lọc Đội Bóng (Phải có mặt trong danh sách)
                is_match_interested = False
                final_league = league_name
                
                for lg, cfg in leagues_config.items():
                    team_list = cfg.get("teams")
                    # Nếu là giải Cup thì lấy hết, nếu giải League thì check tên đội
                    if team_list is None:
                        if lg.lower() in full_lower:
                            is_match_interested = True
                            final_league = lg
                            break
                    else:
                        if any(t in home_team.lower() or t in away_team.lower() for t in team_list):
                            is_match_interested = True
                            final_league = lg
                            break
                            
                # Nếu không khớp bóng đá và cũng không phải tennis thì bỏ qua
                if not is_match_interested and "tennis" not in league_name.lower() and "atp" not in league_name.lower():
                    continue

                # Lấy Logo Kênh Truyền Hình
                channels = []
                for img in card.find_all('img'):
                    alt = img.get('alt', '').replace(' logo', '').strip()
                    # Loại bỏ logo của chính các đội bóng, chỉ giữ lại kênh
                    if alt and home_team.lower() not in alt.lower() and away_team.lower() not in alt.lower():
                        if alt not in channels:
                            channels.append(alt)

                # Lưu kết quả
                all_games.append({
                    "Date": today.strftime("%Y-%m-%d"),
                    "Time": time_text,
                    "League": final_league,
                    "Matchup": matchup,
                    "Channels": channels
                })
                seen_matchups.add(matchup_key)

            except Exception:
                continue

    # Xuất file JSON & In Log
    if all_games:
        with open("wheresthematch.json", 'w', encoding='utf-8') as f:
            json.dump(all_games, f, indent=4, ensure_ascii=False)
        print(f"✅ THÀNH CÔNG: Tìm thấy {len(all_games)} trận hôm nay.")
        for g in all_games:
            print(f"  ⚽ {g['Time']} | {g['Matchup']} | Kênh: {', '.join(g['Channels'])}")
    else:
        print("⚠️ Không tìm thấy trận đấu nào khớp yêu cầu hôm nay.")

if __name__ == "__main__":
    asyncio.run(scrape_wheresthematch())
