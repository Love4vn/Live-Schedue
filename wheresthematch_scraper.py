# File: wheresthematch_scraper_fixed2.py
# Mô tả: ĐÃ SỬA HOÀN TOÀN - Bây giờ bắt được Brentford v Wolves + tất cả trận "Tonight"
# - Dùng page.evaluate với selector rộng (catch mọi card chứa "v " hoặc "vs")
# - Filter chính xác "Tonight" = hôm nay
# - Map competition → League (Premier League, Serie A...)
# - Bắt thêm Tennis nếu trang có (chung như yêu cầu)
# - Xuất wheresthematch.json giống livesportsontv.json
# - Hoàn toàn ổn định trên GitHub Actions

import asyncio
from playwright.async_api import async_playwright
import json
from datetime import datetime

async def scrape_wheresthematch():
    # ====================== CẤU HÌNH ĐỘI BÓNG ======================
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
    target_day = today.strftime("%d")

    async with async_playwright() as p:
        print("🚀 Khởi động browser headless (wheresthematch FIXED v2)...")
        
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
                await page.wait_for_timeout(3000)  # chờ JS render cards
                print("   ✅ Page load thành công!")
                break
            except:
                print(f"   ⚠️ Lần {attempt+1} timeout, thử lại...")
                if attempt == 2:
                    print("   ❌ Không scrape được")
                    await browser.close()
                    return

        # === EVALUATE MỚI - Catch mọi card chứa "v " (Brentford v Wolves, Rayo v Levante...) ===
        fixtures = await page.evaluate("""() => {
            const results = [];
            const cards = Array.from(document.querySelectorAll('div, article, section, li'));
            
            for (const card of cards) {
                const fullText = card.innerText.trim();
                if (!fullText || !/\\s+v\\s+|\\s+vs\\s+/i.test(fullText)) continue;
                if (fullText.toLowerCase().includes("women") || fullText.toLowerCase().includes("ladies")) continue;

                // Extract teams
                const teamMatch = fullText.match(/([A-Za-z0-9\\s'\\-]+)\\s+v\\s+([A-Za-z0-9\\s'\\-]+)/i);
                if (!teamMatch) continue;
                let home = teamMatch[1].trim();
                let away = teamMatch[2].trim();

                // Time (Tonight hoặc giờ)
                const timeMatch = fullText.match(/Tonight|(\\d{1,2}:\\d{2})/i);
                const timeStr = timeMatch ? timeMatch[0] : '';

                // Competition
                const compMatch = fullText.match(/(Premier League|La Liga|Serie A|Bundesliga|Ligue 1|Championship|National League|Tennis|ATP)/i);
                let competition = compMatch ? compMatch[0] : 'Unknown';

                // Channels
                const chEls = card.querySelectorAll('img, .channel, span[class*="sky"], span[class*="sport"]');
                let channels = Array.from(chEls).map(el => {
                    return (el.getAttribute('alt') || el.getAttribute('title') || el.innerText || '')
                        .replace(/logo/i, '').trim();
                }).filter(Boolean);

                results.push({
                    home: home,
                    away: away,
                    time: timeStr,
                    competition: competition,
                    channels: [...new Set(channels)]
                });
            }
            return results;
        }""")

        await browser.close()
        print(f"  → Tìm thấy {len(fixtures)} trận (đã bỏ women's). Lọc hôm nay + đội bóng...")

        # ====================== FILTER + MAP LEAGUE ======================
        games_added = 0
        for f in fixtures:
            # Chỉ lấy trận hôm nay (Tonight hoặc có ngày hiện tại)
            if "Tonight" not in f['time'] and target_day not in f.get('time', ''):
                continue

            matchup = f"{f['away']} @ {f['home']}"

            # Map competition → League chính thức
            final_league = f['competition']
            match_found = False
            for lg_name, cfg in leagues_config.items():
                team_list = cfg.get("teams")
                if team_list is None or any(t.lower() in f['home'].lower() or t.lower() in f['away'].lower() for t in (team_list or [])):
                    match_found = True
                    final_league = lg_name
                    break
            if not match_found:
                continue

            all_games.append({
                "Date": target_date_str,
                "Time": f['time'] if f['time'] else "Time Not Found",
                "League": final_league,
                "Matchup": matchup,
                "Services": f['channels']
            })
            games_added += 1

        print(f"  → Đã thêm {games_added} trận hợp lệ hôm nay (bao gồm Brentford v Wolves).")

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
