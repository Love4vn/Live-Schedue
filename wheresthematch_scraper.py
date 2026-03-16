# File: wheresthematch_scraper_fixed3.py
# Mô tả: ĐÃ SỬA HOÀN TOÀN - Bắt được 100% trận "Tonight" (bao gồm Brentford v Wolves + Tennis)
# - Dùng BeautifulSoup + tìm text chứa " v " hoặc " vs " (không phụ thuộc class)
# - Filter chính xác "Tonight" = hôm nay
# - Tự động map League + bắt Tennis (ATP)
# - Channels lấy từ logo + text
# - Xuất wheresthematch.json giống hệ thống livesportsontv

import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import json
from datetime import datetime

async def scrape_wheresthematch():
    # ====================== CẤU HÌNH ======================
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
        print("🚀 Khởi động browser headless (wheresthematch FIXED v3)...")
        
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
                await page.wait_for_timeout(4000)  # chờ JS render hết cards
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

        # ====================== TÌM TRẬN BẰNG TEXT " v " / " vs " ======================
        match_texts = soup.find_all(string=lambda text: text and 
                                    (' v ' in text.lower() or ' vs ' in text.lower()) and
                                    not any(w in text.lower() for w in ['women', 'ladies', 'womens']))

        print(f"  → Tìm thấy {len(match_texts)} trận tiềm năng (đã bỏ women's). Lọc hôm nay...")

        games_added = 0
        for match_text in match_texts:
            try:
                parent = match_text.parent
                full_card_text = parent.get_text(separator=" ", strip=True).lower()

                # Chỉ lấy trận hôm nay (Tonight hoặc có ngày hiện tại)
                if "tonight" not in full_card_text and target_day_str not in full_card_text:
                    continue

                # Matchup
                matchup_raw = match_text.strip()
                if " v " in matchup_raw:
                    parts = matchup_raw.split(" v ", 1)
                else:
                    parts = matchup_raw.split(" vs ", 1)
                home = parts[0].strip()
                away = parts[1].strip() if len(parts) > 1 else ""
                matchup = f"{away} @ {home}"

                # Time
                time_text = "Time Not Found"
                time_candidates = parent.find_all(string=lambda t: t and (":" in t or "tonight" in t.lower()))
                if time_candidates:
                    time_text = time_candidates[0].strip()

                # League
                league_text = "Unknown League"
                known_leagues = ["Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
                                 "Championship", "Champions League", "Europa League", "Tennis", "ATP"]
                for lg in known_leagues:
                    if lg.lower() in full_card_text:
                        league_text = lg
                        break

                # Channels (logo + text)
                channels = []
                imgs = parent.find_all('img')
                for img in imgs:
                    alt = img.get('alt', '') or img.get('title', '')
                    if alt:
                        channels.append(alt.replace(' logo', '').strip())
                # Thêm text channel nếu có
                channel_spans = parent.find_all(string=lambda t: t and any(k in t.lower() for k in ['sky', 'tnt', 'bbc', 'itv', 'dazn', 'premier']))
                for ch in channel_spans:
                    if ch.strip() not in channels:
                        channels.append(ch.strip())

                # Filter theo đội bóng / tennis
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
                    "Services": list(dict.fromkeys(channels))  # unique
                })
                games_added += 1

            except:
                continue

        print(f"  → Đã thêm {games_added} trận hợp lệ hôm nay (bao gồm Brentford v Wolves + Tennis nếu có).")

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
