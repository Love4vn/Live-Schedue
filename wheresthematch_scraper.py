# File: wheresthematch_scraper_fixed.py
# Mô tả: ĐÃ SỬA HOÀN TOÀN - Timeout + Site đã thay đổi HTML (2026)
# - Dùng "domcontentloaded" + wait_for_selector('table')
# - Chuyển sang BeautifulSoup (ổn định hơn evaluate JS cũ)
# - Parse table mới (cột TV Fixtures + When + Competition + Channels)
# - Giữ filter "hôm nay" + đội bóng (Premier League, Serie A...) + bỏ women's
# - Xuất wheresthematch.json giống livesportsontv

import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import json
from datetime import datetime

async def scrape_wheresthematch():
    leagues_config = {
        "Premier League": {"teams": {"arsenal", "aston villa", "bournemouth", "brentford", "brighton",
                                     "chelsea", "crystal palace", "everton", "fulham", "leeds united",
                                     "liverpool", "manchester city", "manchester united", "newcastle",
                                     "nottingham forest", "sunderland", "tottenham hotspur",
                                     "west ham united", "wolverhampton"}},
        "Serie A": {"teams": {"inter milan", "ac milan", "napoli", "juventus", "roma",
                              "atalanta", "lazio"}},
        "La Liga": {"teams": {"barcelona", "real madrid", "atlético"}},
        "Bundesliga": {"teams": {"bayern", "borussia dortmund", "bayer leverkusen"}},
        "Ligue 1": {"teams": {"psg", "olympique marseille"}},
        "UEFA Champions League": {"teams": None},
        "UEFA Europa League": {"teams": None},
        "UEFA Europa Conference League": {"teams": None},
    }

    all_games = []
    today = datetime.now()
    target_date_str = today.strftime("%Y-%m-%d")

    async with async_playwright() as p:
        print("🚀 Khởi động browser headless (wheresthematch FIXED)...")
        
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        page = await browser.new_page()
        
        page.set_default_navigation_timeout(120000)
        page.set_default_timeout(60000)

        url = "https://www.wheresthematch.com/live-football-on-tv/"
        print(f"--- Đang scrape {url} ---")

        success = False
        for attempt in range(3):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=120000)
                await page.wait_for_selector('table', timeout=30000)  # Chờ table load
                print("   ✅ Page + Table đã load thành công!")
                success = True
                break
            except Exception as e:
                print(f"   ⚠️ Lần {attempt+1}/3 timeout, thử lại...")
                await page.wait_for_timeout(3000)

        if not success:
            print("   ❌ Không scrape được sau 3 lần, bỏ qua")
            await browser.close()
            return

        # === Parse bằng BeautifulSoup (site đã đổi cấu trúc) ===
        html = await page.content()
        soup = BeautifulSoup(html, 'html.parser')
        
        # Tìm tất cả hàng trong bảng (cột: TV Fixtures | When | Competition | Channels)
        rows = soup.find_all('tr')
        print(f"  → Tìm thấy {len(rows)} hàng bảng. Lọc hôm nay + đội bóng...")

        games_added = 0
        for row in rows:
            try:
                tds = row.find_all('td')
                if len(tds) < 4:
                    continue

                # Cột 1-2: TV Fixtures (matchup)
                fixture_text = ' '.join(tds[1].stripped_strings).strip()
                if not fixture_text or "women" in fixture_text.lower() or "ladies" in fixture_text.lower():
                    continue

                # Cột 3: When (time + "Today")
                time_cell = tds[2].get_text(strip=True)
                if "today" not in time_cell.lower() and today.strftime("%d") not in time_cell:
                    continue

                # Cột 4: Competition (League)
                comp_cell = tds[3].get_text(strip=True)
                league_name = comp_cell or "Unknown League"

                # Cột 5: Channels
                channels = []
                channel_cell = tds[4] if len(tds) > 4 else None
                if channel_cell:
                    channels = [ch.strip() for ch in channel_cell.stripped_strings if ch.strip()]

                # Tạo matchup (nếu có "v" hoặc team names)
                matchup = fixture_text
                if " @ " not in matchup and " v " not in matchup.lower():
                    matchup = f"{fixture_text} (Event)"

                # Filter đội bóng (giống livesportsontv)
                match_found = False
                final_league = league_name
                for lg, cfg in leagues_config.items():
                    team_list = cfg.get("teams")
                    if team_list is None or any(t.lower() in fixture_text.lower() for t in team_list):
                        match_found = True
                        final_league = lg
                        break
                if not match_found:
                    continue

                all_games.append({
                    "Date": target_date_str,
                    "Time": time_cell.split('*')[-1].strip() if '*' in time_cell else time_cell,
                    "League": final_league,
                    "Matchup": matchup,
                    "Services": channels
                })
                games_added += 1

            except:
                continue

        await browser.close()
        print(f"  → Đã thêm {games_added} trận hợp lệ hôm nay.")

    # ====================== XUẤT JSON ======================
    filename = "wheresthematch.json"
    if all_games:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(all_games, f, indent=4, ensure_ascii=False)
        print(f"\n🎉 THÀNH CÔNG: {len(all_games)} trận!")
        print(f"📁 File: {filename} (sẵn sàng commit lên GitHub)")
    else:
        print("⚠️ Không có trận nào hôm nay.")

if __name__ == "__main__":
    asyncio.run(scrape_wheresthematch())
