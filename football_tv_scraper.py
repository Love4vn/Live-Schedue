# scraper.py
# Python + Playwright - Chạy trên GitHub Actions
# Lấy lịch Ngoại hạng Anh + kênh TV từ LiveFootballOnTV & Where's The Match
# Xuất premier_league_tv.json (giờ Việt Nam UTC+7)

import asyncio
import json
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

def vn_time(uk_str: str):
    """Chuyển giờ UK (ví dụ: 15:00 hoặc Sat 21 Mar 12:30) sang giờ VN"""
    try:
        # Giả sử năm hiện tại hoặc +1 nếu cần
        now = datetime.now()
        if "Mar" in uk_str or "March" in uk_str:
            year = now.year if now.month >= 3 else now.year + 1
        else:
            year = now.year
        # Parse đơn giản
        dt = datetime.strptime(uk_str.replace(" *", " "), "%a %d %b %Y %H:%M") if " " in uk_str and ":" in uk_str else None
        if dt:
            vn = dt + timedelta(hours=7)
            return vn.strftime("%Y-%m-%d %H:%M VN")
    except:
        pass
    return uk_str + " (VN)"

async def scrape_livefootballontv():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.live-footballontv.com", wait_until="networkidle")
        
        fixtures = await page.evaluate("""() => {
            const lines = document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);
            const dayRegex = /^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)/i;
            const timeRegex = /^(\\d{1,2}:\\d{2})/;
            const vsRegex = /\\s+v(?:s)?\\s+/i;
            const results = [];
            let currentDate = null;

            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];
                if (dayRegex.test(line)) { currentDate = line; continue; }
                if (!currentDate) continue;

                const timeMatch = line.match(timeRegex);
                if (timeMatch) {
                    const timeString = timeMatch[1];
                    const teamLine = lines[i-1] || '';
                    const vsMatch = vsRegex.exec(teamLine);
                    if (!vsMatch) continue;

                    const home = teamLine.substring(0, vsMatch.index).trim();
                    const away = teamLine.substring(vsMatch.index + vsMatch[0].length).trim();
                    let comp = lines[i-2] && !dayRegex.test(lines[i-2]) ? lines[i-2] : '';

                    // Channels
                    let channels = [];
                    for (let j = i+1; j < i+5 && j < lines.length; j++) {
                        const next = lines[j].toLowerCase();
                        if (dayRegex.test(lines[j]) || timeRegex.test(lines[j])) break;
                        if (next.includes('sky') || next.includes('tnt') || next.includes('bbc') || next.includes('itv') || next.includes('amazon')) {
                            channels.push(lines[j].replace(/📺/g, '').trim());
                        }
                    }

                    if (comp.toLowerCase().includes('premier league') || comp.toLowerCase().includes('epl')) {
                        results.push({
                            homeTeam: home,
                            awayTeam: away,
                            kickoffUK: timeString,
                            competition: comp,
                            channels: [...new Set(channels)],
                            source: "livefootballontv"
                        });
                    }
                }
            }
            return results;
        }""")
        await browser.close()
        return fixtures

async def scrape_wheresthematch():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.wheresthematch.com/live-football-on-tv/", wait_until="networkidle")
        
        fixtures = await page.evaluate("""() => {
            const rows = Array.from(document.querySelectorAll('table tr'));
            const results = [];
            rows.forEach(row => {
                const cells = row.querySelectorAll('td');
                if (cells.length < 3) return;
                const when = cells[0].innerText.trim();           // Sat 21 Mar 12:30
                const comp = cells[1].innerText.trim();
                const chanCell = cells[2] ? cells[2].innerText.trim() : '';
                const teams = row.querySelectorAll('td.fixture-details a[title]');
                if (teams.length >= 2 && (comp.toLowerCase().includes('premier') || comp.toLowerCase().includes('epl'))) {
                    results.push({
                        homeTeam: teams[0].getAttribute('title'),
                        awayTeam: teams[teams.length-1].getAttribute('title'),
                        kickoffUK: when,
                        competition: comp,
                        channels: chanCell ? chanCell.split(',').map(c => c.trim()) : [],
                        source: "wheresthematch"
                    });
                }
            });
            return results;
        }""")
        await browser.close()
        return fixtures

async def main():
    print("🔄 Đang scrape LiveFootballOnTV + Where's The Match...")
    lfotv = await scrape_livefootballontv()
    wtm = await scrape_wheresthematch()

    # Merge & dedup
    all_fixtures = lfotv + wtm
    seen = {}
    final = []
    for f in all_fixtures:
        key = f"{f['homeTeam']}-{f['awayTeam']}-{f['kickoffUK']}"
        if key not in seen:
            seen[key] = True
            f['kickoffVN'] = vn_time(f['kickoffUK'])
            final.append(f)

    today = datetime.now().strftime("%Y-%m-%d")
    data = {
        "date": today,
        "sport": "Premier League",
        "total": len(final),
        "sources": ["livefootballontv", "wheresthematch"],
        "fixtures": final
    }

    with open("premier_league_tv.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ Hoàn thành! {len(final)} trận Ngoại hạng Anh có kênh TV")
    print("   → File: premier_league_tv.json (giờ Việt Nam)")

if __name__ == "__main__":
    asyncio.run(main())
