import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import json
from datetime import datetime

async def scrape_wheresthematch():
    # Danh sách đội bóng quan tâm
    interested_teams = {
        "brentford", "wolves", "arsenal", "chelsea", "liverpool", 
        "man city", "man utd", "tottenham", "real madrid", "barcelona"
    }

    async with async_playwright() as p:
        print("🚀 Khởi động trình duyệt (Bản V9: Stealth Mode)...")
        # Thêm các args để vượt qua rào cản bot
        browser = await p.chromium.launch(headless=True, args=[
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox'
        ])
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        
        page = await context.new_page()
        url = "https://www.wheresthematch.com/live-football-on-tv/"
        
        try:
            # Tăng timeout và thử tải trang
            print(f"📡 Đang kết nối tới: {url}")
            response = await page.goto(url, wait_until="domcontentloaded", timeout=90000)
            
            if response.status != 200:
                print(f"❌ Trang web phản hồi lỗi: {response.status}")
                await browser.close()
                return

            # Chờ thêm một chút để script bảo mật của trang web chạy xong
            await asyncio.sleep(5)
            
            # Cuộn xuống để load dữ liệu
            await page.evaluate("window.scrollTo(0, 1500)")
            await asyncio.sleep(2)
            
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            
        except Exception as e:
            print(f"❌ Lỗi kết nối (Connection Reset): {e}")
            await browser.close()
            return

        all_games = []
        today_str = datetime.now().strftime("%d").lstrip('0') # Ví dụ: "16"

        # Tìm các khối ngày
        groups = soup.select('.fixtures-group')
        print(f"🔍 Đang phân tích {len(groups)} nhóm ngày...")

        for group in groups:
            date_text = group.select_one('.fixture-date-wrapper').get_text(strip=True).lower() if group.select_one('.fixture-date-wrapper') else ""
            
            # Chỉ xử lý nếu là ngày hôm nay
            if "today" in date_text or today_str in date_text:
                matches = group.select('.fixture-item')
                for match in matches:
                    try:
                        home = match.select_one('.team-home').get_text(strip=True)
                        away = match.select_one('.team-away').get_text(strip=True)
                        matchup = f"{home} vs {away}"
                        
                        time_val = match.select_one('.kick-off-time').get_text(strip=True) if match.select_one('.kick-off-time') else "Live"
                        
                        # Lấy kênh từ logo
                        channels = []
                        logos = match.select('.broadcaster-logos img')
                        for img in logos:
                            alt = img.get('alt', '').replace(' logo', '').strip()
                            if alt: channels.append(alt)
                        
                        # Lọc: Chỉ lấy nếu trùng đội bóng hoặc có kênh Sky/TNT/beIN
                        match_lower = matchup.lower()
                        if any(team in match_lower for team in interested_teams):
                            all_games.append({
                                "Time": time_val,
                                "Matchup": matchup,
                                "Channels": channels
                            })
                    except:
                        continue
        
        await browser.close()

        if all_games:
            print(f"✅ Đã tìm thấy {len(all_games)} trận đấu phù hợp!")
            with open("wheresthematch.json", "w", encoding="utf-8") as f:
                json.dump(all_games, f, indent=4, ensure_ascii=False)
            for g in all_games:
                print(f"  ⚽ {g['Time']} | {g['Matchup']} | Kênh: {', '.join(g['Channels'])}")
        else:
            print("⚠️ Không tìm thấy trận nào khớp với tiêu chí lọc của bạn.")

if __name__ == "__main__":
    asyncio.run(scrape_wheresthematch())
