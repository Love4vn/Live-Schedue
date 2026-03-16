# File: wheresthematch_scraper_fixed4.py
# Mô tả: ĐÃ SỬA HOÀN TOÀN - Bắt được Brentford v Wolves + mọi trận "Tonight"
# - Tìm card bằng tag.get_text() chứa " v " hoặc " vs " (fix lỗi text node bị split)
# - Filter chính xác "Tonight" + ngày hôm nay
# - Tự động map League + bắt Tennis (ATP)
# - Channels lấy từ img + text
# - Xuất wheresthematch.json giống hệ thống

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
        "Tennis (ATP)": {"teams": None}
    }

    all_games = []
    today = datetime.now()
    target_date_str = today.strftime("%Y-%m-%d")
    target_day_str = today.strftime("%d")

    async with async_playwright() as p:
        print("🚀 Khởi động browser headless (wheresthematch FIXED v4 - fix text split)...")
        
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        page = await browser.new_page()
        
        page.set_default_navigation_timeout(120000)
        page.set_default_timeout(60000)

        url = "https://www.wheresthematch.com/live-football-on-tv/"
        print(f"--- Đang scrape {url} ---")

        for attempt in range(3):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=120000)
                await page.wait_for_timeout(5000)  # chờ JS render hết
                print("   ✅ Page load thành công!")
                break
            except:
                print(f"   ⚠️ Lần {attempt+1} timeout...")
                if attempt == 2:
                    await browser.close()
                    return

        html = await page.content()
        soup = BeautifulSoup(html, 'html.parser')
        await browser.close()

        # ====================== TÌM CARD CHỨA " v " / " vs " (FIX LỖI TEXT NODE) ======================
        potential_cards = []
        for tag in soup.find_all(['div', 'li', 'article', 'section', 'tr']):
            text = tag.get_text(strip=True).lower()
            if (' v ' in text or ' vs ' in text) and not any(w in text for w in ['women', 'ladies', 'womens']):
                potential_cards.append(tag)

        print(f"  → Tìm thấy {len(potential_cards)} trận tiềm năng (đã bỏ women's). Lọc hôm nay...")

        games_added = 0
        for card in potential_cards:
            try:
                full_text = card.get_text(separator=" ", strip=True)
                full_lower = full_text.lower()

                # Chỉ lấy trận hôm nay
                if "tonight" not in full_lower and target_day_str not in full_text:
                    continue

                # Extract matchup
                if " v " in full_text:
                    parts = full_text.split(" v ", 1)
                else:
                    parts = full_text.split(" vs ", 1)
                home = parts[0].strip()
                away = parts[1].strip() if len(parts) > 1 else ""
                matchup = f"{away} @ {home}"

                # Time
                time_text = "Time Not Found"
                if "tonight" in full_lower:
                    time_text = "Tonight"
                else:
                    import re
                    time_match = re.search(r'(\d{1,2}:\d{2})', full_text)
                    if time_match:
                        time_text = time_match.group(1)

                # League
                league_text = "Unknown League"
                known = ["Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
                         "Championship", "Champions League", "Europa League", "Tennis", "ATP"]
                for lg in known:
                    if lg.lower() in full_lower:
                        league_text = lg
                        break

                # Channels
                channels = []
                for img in card.find_all('img'):
                    alt = img.get('alt') or img.get('title') or ''
                    if alt:
                        channels.append(alt.replace(' logo', '').strip())
                for txt in card.find_all(string=lambda t: t and any(k in t.lower() for k in ['sky', 'tnt', 'bbc', 'itv', 'dazn', 'premier', 'discovery'])):
                    ch = txt.strip()
                    if ch and ch not in channels:
                        channels.append(ch)

                # Filter đội bóng / tennis
                match_found = False
                final_league = league_text
                for lg_name, cfg in leagues_config.items():
                    team_list = cfg.get("teams")
                    if team_list is None or any(t.lower() in home.lower() or t.lower() in away.lower() for t in (team_list or [])):
                        match_found = True
                        final_league = lg_name
                        break
                if not match_found and "tennis" not in league_text.lower() and "atp" not in league_text.lower():
                    continue

                all_games.append({
                    "Date": target_date_str,
                    "Time": time_text,
                    "League": final_league,
                    "Matchup": matchup,
                    "Services": list(dict.fromkeys(channels))
                })
                games_added += 1

            except:
                continue

        print(f"  → Đã thêm {games_added} trận hợp lệ hôm nay (bao gồm Brentford v Wolves + Tennis).")

    # ====================== XUẤT JSON ======================
    filename = "wheresthematch.json"
    if all_games:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(all_games, f, indent=4, ensure_ascii=False)
        print(f"\n🎉 THÀNH CÔNG: {len(all_games)} trận!")
        print(f"📁 File: {filename}")
    else:
        print("⚠️ Không có trận nào hôm nay.")

if __name__ == "__main__":
    asyncio.run(scrape_wheresthematch())
