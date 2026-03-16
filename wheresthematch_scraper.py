# File: wheresthematch_scraper.py
# Mô tả: Scraper Python (Playwright) cho https://www.wheresthematch.com/live-football-on-tv/
# - Dịch trực tiếp từ wheresthematch.js bạn gửi (giữ nguyên logic team, channel, skip women's)
# - Thêm filter "hôm nay" + filter đội bóng giống livesportsontv (Premier League, Serie A...)
# - Xuất file: wheresthematch.json (định dạng giống schedule_livesportsontv.json)
# - Đã fix ổn định cho GitHub Actions (timeout, retry, no-sandbox)

import asyncio
from playwright.async_api import async_playwright
import json
from datetime import datetime

async def scrape_wheresthematch():
    # ====================== CẤU HÌNH GIẢI ĐẤU & ĐỘI BÓNG ======================
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
    target_day_name = today.strftime("%a")  # Mon, Tue...

    async with async_playwright() as p:
        print("🚀 Khởi động browser headless (wheresthematch)...")
        
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        page = await browser.new_page()
        
        page.set_default_navigation_timeout(90000)
        page.set_default_timeout(60000)

        url = "https://www.wheresthematch.com/live-football-on-tv/"
        print(f"--- Đang scrape {url} ---")

        for attempt in range(2):
            try:
                await page.goto(url, wait_until="networkidle2", timeout=90000)
                break
            except Exception as e:
                print(f"   ⚠️ Timeout lần {attempt+1}, thử lại...")
                if attempt == 1:
                    print("   ❌ Không scrape được, bỏ qua")
                    await browser.close()
                    return

        # === DÙNG ĐÚNG LOGIC JS BẠN GỬI (page.evaluate) ===
        fixtures = await page.evaluate("""(UK_CHANNELS) => {
            const results = [];
            const rows = Array.from(document.querySelectorAll('tr[itemscope][itemtype*="BroadcastEvent"]'));
            
            rows.forEach(row => {
                try {
                    const rowText = row.innerText.toLowerCase();
                    if (rowText.includes("women's") || rowText.includes('womens') || rowText.includes('ladies')) return;

                    const fixtureCell = row.querySelector('td.fixture-details');
                    const startCell = row.querySelector('td.start-details');
                    const compCell = row.querySelector('td.competition-name');
                    const chanCell = row.querySelector('td.channel-details');

                    if (!fixtureCell || !startCell) return;

                    const fixtureText = fixtureCell.innerText.trim();
                    let homeTeam = '';
                    let awayTeam = '';

                    const teamLinks = Array.from(fixtureCell.querySelectorAll('span.fixture a[title]'));
                    if (teamLinks.length >= 2) {
                        homeTeam = teamLinks[0].getAttribute('title') || teamLinks[0].innerText;
                        awayTeam = teamLinks[teamLinks.length-1].getAttribute('title') || teamLinks[teamLinks.length-1].innerText;
                    } else {
                        const vsMatch = fixtureText.match(/([A-Za-z\\s\\-'.0-9]+)\\s+(?:v|vs|versus|–|-)\\s+([A-Za-z\\s\\-'.0-9]+)/i);
                        if (vsMatch) {
                            homeTeam = vsMatch[1];
                            awayTeam = vsMatch[2];
                        }
                    }

                    homeTeam = (homeTeam || '').trim().replace(/\\b(fc|afc|cf|sc|ac)\\b/gi, '').replace(/\\s+/g, ' ').trim();
                    awayTeam = (awayTeam || '').trim().replace(/\\b(fc|afc|cf|sc|ac)\\b/gi, '').replace(/\\s+/g, ' ').trim();
                    if (!homeTeam || !awayTeam) return;

                    let kickoff = startCell.getAttribute('content') || '';
                    if (!kickoff) {
                        const meta = row.querySelector('meta[itemprop="startDate"]');
                        if (meta) kickoff = meta.getAttribute('content') || '';
                    }

                    let competition = '';
                    if (compCell) {
                        const span = compCell.querySelector('span');
                        competition = (span ? span.innerText : compCell.innerText || '').trim();
                    }

                    const channels = [];
                    if (chanCell) {
                        const text = chanCell.innerText.trim();
                        for (const ch of UK_CHANNELS) {
                            if (text.toLowerCase().includes(ch.toLowerCase())) channels.push(ch);
                        }
                        const logos = Array.from(chanCell.querySelectorAll('img'));
                        logos.forEach(img => {
                            let name = (img.getAttribute('title') || img.getAttribute('alt') || '').replace(/logo/i, '').trim();
                            if (name) channels.push(name);
                        });
                    }

                    results.push({
                        home: homeTeam,
                        away: awayTeam,
                        kickoffUtc: kickoff,
                        competition: competition,
                        channels: [...new Set(channels.map(ch => ch.trim()))]
                    });
                } catch (e) {}
            });
            return results;
        }""", [
            'Sky Sports Main Event','Sky Sports Premier League','Sky Sports Football','Sky Sports Arena',
            'Sky Sports Action','Sky Sports Mix','Sky Sports News','Sky Sports+','TNT Sports 1',
            'TNT Sports 2','TNT Sports 3','TNT Sports 4','BBC One','BBC Two','ITV1','ITV4',
            'Amazon Prime Video','Premier Sports 1','DAZN'
        ])

        await browser.close()

        # ====================== FILTER HÔM NAY + ĐỘI BÓNG ======================
        print(f"  → Tìm thấy {len(fixtures)} trận (đã bỏ women's). Lọc hôm nay + đội bóng...")

        games_added = 0
        for f in fixtures:
            # Lọc hôm nay (dùng text "Today" hoặc ngày hiện tại)
            if not f['kickoffUtc'] or "today" not in f['kickoffUtc'].lower():
                continue

            matchup = f"{f['away']} @ {f['home']}"
            comp = f['competition'] or "Unknown League"

            # Filter theo đội (giống livesportsontv)
            match_found = False
            for league_name, cfg in leagues_config.items():
                team_list = cfg["teams"]
                if team_list is None or any(t.lower() in f['home'].lower() or t.lower() in f['away'].lower() for t in team_list):
                    match_found = True
                    league_name_final = league_name
                    break
            if not match_found:
                continue

            all_games.append({
                "Date": target_date_str,
                "Time": f['kickoffUtc'].split('T')[-1][:5] if 'T' in f['kickoffUtc'] else "Time Not Found",
                "League": league_name_final,
                "Matchup": matchup,
                "Services": f['channels']
            })
            games_added += 1

        print(f"  → Đã thêm {games_added} trận hợp lệ hôm nay.")

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
