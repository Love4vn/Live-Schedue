import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

async def scrape_wheresthematch():
    # Danh sách từ khóa cần tìm (không phân biệt hoa thường)
    keywords = ["brentford", "wolves", "arsenal", "chelsea", "liverpool", "man city", "man utd", "tottenham"]

    async with async_playwright() as p:
        print("🚀 Khởi động trình duyệt (Bản V10: XPath & Regex Scanner)...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            await page.goto("https://www.wheresthematch.com/live-football-on-tv/", wait_until="networkidle", timeout=60000)
            # Cuộn trang sâu để đảm bảo dữ liệu hiển thị
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
            await asyncio.sleep(3)
            
            # Lấy toàn bộ HTML sau khi đã render xong
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
        except Exception as e:
            print(f"❌ Lỗi: {e}")
            await browser.close()
            return

        await browser.close()
        all_games = []

        # Tìm tất cả các thẻ chứa thông tin trận đấu (thường là .fixture-item)
        items = soup.find_all(class_=re.compile("fixture-item|match-item"))
        
        for item in items:
            full_text = item.get_text(" ", strip=True)
            text_lower = full_text.lower()

            # 1. Kiểm tra xem có chứa từ khóa đội bóng mình cần không
            if any(k in text_lower for k in keywords):
                try:
                    # Tách tên đội (thường cách nhau bởi chữ 'v' hoặc 'vs')
                    # Tìm thẻ chứa team-home/away hoặc dùng regex bóc tách
                    home = item.select_one('.team-home, .team-name')
                    away = item.select_one('.team-away, .team-name:nth-of-type(2)')
                    
                    home_name = home.get_text(strip=True) if home else "Unknown"
                    away_name = away.get_text(strip=True) if away else "Unknown"
                    
                    # Nếu lấy class bị lỗi, dùng Regex bóc từ full_text
                    if home_name == "Unknown":
                        match = re.search(r'([A-Za-z\s]+)\sv\s([A-Za-z\s]+)', full_text)
                        if match:
                            home_name, away_name = match.groups()

                    time_match = re.search(r'(\d{1,2}:\d{2})', full_text)
                    kickoff = time_match.group(1) if time_match else "Live/Tonight"

                    # Lấy kênh phát sóng (quan trọng nhất)
                    channels = []
                    for img in item.find_all('img'):
                        alt = img.get('alt', '').replace(' logo', '').strip()
                        if alt and home_name not in alt and away_name not in alt:
                            channels.append(alt)
                    
                    # Nếu ko có ảnh, tìm text đài truyền hình
                    if not channels:
                        broadcaster = item.select_one('.broadcaster-name, .channel')
                        if broadcaster: channels.append(broadcaster.get_text(strip=True))

                    all_games.append({
                        "Time": kickoff,
                        "Matchup": f"{home_name} vs {away_name}",
                        "Channels": list(dict.fromkeys(channels))
                    })
                except:
                    continue

    # Lưu và in kết quả
    if all_games:
        with open("wheresthematch.json", "w", encoding="utf-8") as f:
            json.dump(all_games, f, indent=4, ensure_ascii=False)
        print(f"✅ ĐÃ TÌM THẤY {len(all_games)} TRẬN!")
        for g in all_games:
            print(f"  ⚽ {g['Time']} | {g['Matchup']} | Kênh: {', '.join(g['Channels'])}")
    else:
        print("⚠️ Vẫn chưa tìm thấy trận nào. Có thể trang web đang hiển thị cấu trúc khác. Bạn hãy thử mở file wheresthematch.json xem có nội dung gì không nhé.")

if __name__ == "__main__":
    asyncio.run(scrape_wheresthematch())
