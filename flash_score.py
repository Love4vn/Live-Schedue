# flash_score.py - PHIÊN BẢN ĐÃ SỬA HOÀN CHỈNH CHO YÊU CẦU CỦA BẠN
# ✅ Chuyển từ chỉ LIVE → LỊCH TRẬN ĐẤU (today + upcoming/scheduled)
# ✅ Sửa selector để lấy tất cả trận (div.event__match thay vì --live)
# ✅ Thêm trường "tv_channels" + "broadcast_info" (kênh truyền hình / livestream)
#     Flashscore chỉ có một số trận hiển thị TV, nên mình thêm gợi ý M3U của bạn
# ✅ Vẫn giữ filter đúng các đội/league bạn yêu cầu (Premier League, Serie A, ...)
# ✅ Tennis ATP + Grand Slam vẫn giữ
# ✅ Chạy 1 lần, phù hợp GitHub Actions (không loop vô tận)
# ✅ Xuất flashscore.json với đầy đủ lịch + kênh gợi ý

import asyncio
import json
from datetime import datetime, timezone
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# ==================================================
# Helper: safe int
# ==================================================
def to_int(val: str) -> int:
    val = val.strip()
    return int(val) if val.isdigit() else 0

# ==================================================
# Danh sách giải + đội bạn yêu cầu
# ==================================================
LEAGUE_TEAMS = {
    "premier league": ["arsenal", "aston villa", "bournemouth", "brentford", "brighton",
                       "chelsea", "crystal palace", "everton", "fulham", "leeds united",
                       "liverpool", "manchester city", "manchester united", "newcastle",
                       "nottingham forest", "sunderland", "tottenham hotspur",
                       "west ham united", "wolverhampton"],
    "serie a": ["inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"],
    "la liga": ["barcelona", "real madrid", "atlético"],
    "bundesliga": ["bayern", "borussia dortmund", "bayer leverkusen"],
    "ligue 1": ["psg", "olympique marseille"],
    "champions league": None,
    "europa league": None,
    "conference league": None,
}

# ==================================================
# Extract match detail + TV/broadcast info
# ==================================================
async def extract_match_detail(page):
    try:
        breadcrumbs = page.locator('[data-testid="wcl-breadcrumbsItem"] span[itemprop="name"]')
        breadcrumb_texts = await breadcrumbs.all_inner_texts()

        sport = breadcrumb_texts[0].lower()
        country = breadcrumb_texts[1].upper() if len(breadcrumb_texts) > 1 else ""
        league_raw = breadcrumb_texts[2].strip() if len(breadcrumb_texts) > 2 else ""
        league = league_raw.split("-")[0].strip()
        season = "2025/26"

        home_team = await page.locator('.duelParticipant__home .participant__participantName a').inner_text()
        away_team = await page.locator('.duelParticipant__away .participant__participantName a').inner_text()

        start_time_text = await page.locator('.duelParticipant__startTime').inner_text()
        start_dt = datetime.strptime(start_time_text.strip(), "%d.%m.%Y %H:%M").replace(tzinfo=timezone.utc)

        match_period = await page.locator('.detailScore__status .fixedHeaderDuel__detailStatus').inner_text()

        period_text = match_period.lower()
        if any(x in period_text for x in ["live", "quarter", "half", "break", "ot"]):
            status = "live"
        elif any(x in period_text for x in ["finished", "final"]):
            status = "finished"
        else:
            status = "scheduled"

        score_values = await page.locator('.detailScore__wrapper span').all_inner_texts()
        home_score = to_int(score_values[0]) if len(score_values) > 0 else 0
        away_score = to_int(score_values[2]) if len(score_values) > 2 else 0

        home_parts = await page.locator('.smh__home.smh__part--1, .smh__home.smh__part--2, .smh__home.smh__part--3, .smh__home.smh__part--4').all_inner_texts()
        away_parts = await page.locator('.smh__away.smh__part--1, .smh__away.smh__part--2, .smh__away.smh__part--3, .smh__away.smh__part--4').all_inner_texts()

        home_parts += [""] * (4 - len(home_parts))
        away_parts += [""] * (4 - len(away_parts))

        q1h, q2h, q3h, q4h = map(to_int, home_parts[:4])
        q1a, q2a, q3a, q4a = map(to_int, away_parts[:4])

        # ==================== KÊNH TRUYỀN HÌNH / LIVESTREAM ====================
        tv_channels = []
        try:
            # Flashscore thường hiển thị TV ở khu vực này
            tv_elements = await page.locator('.tvChannel, .broadcast__channel, [class*="tv"], text=TV, text=Channel').all_inner_texts()
            tv_channels = [t.strip() for t in tv_elements if t.strip()]
        except:
            pass

        # Nếu không tìm thấy thì gợi ý dùng M3U của bạn
        if not tv_channels:
            tv_channels = ["Livestream IPTV - Kênh Thể Thao trong file M3U của bạn (output.m3u)"]

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sport": sport,
            "country": country,
            "league": league,
            "season": season,
            "home_team": home_team,
            "away_team": away_team,
            "match_start_time_UTC": start_dt.isoformat(),
            "match_period": match_period,
            "status": status,
            "match_url": page.url,
            "score": {
                "current": {"home": home_score, "away": away_score},
                "periods": {"q1": {"home": q1h, "away": q1a}, "q2": {"home": q2h, "away": q2a},
                            "q3": {"home": q3h, "away": q3a}, "q4": {"home": q4h, "away": q4a}},
                "halves": {"first_half": {"home": q1h + q2h, "away": q1a + q2a},
                           "second_half": {"home": q3h + q4h, "away": q3a + q4a}}
            },
            "tv_channels": tv_channels,
            "broadcast_info": "Kiểm tra Flashscore hoặc dùng M3U Thể Thao để xem livestream"
        }
    except Exception as e:
        print(f"❌ Extract error: {e}")
        return None

# ==================================================
# Fetch match URLs (LỊCH + LIVE)
# ==================================================
async def fetch_match_urls(page, target_url: str):
    try:
        await page.goto(target_url, wait_until="networkidle")
        await page.wait_for_selector("div.event__match", timeout=20000)
        matches = page.locator("div.event__match")
        count = await matches.count()
        print(f"🟢 Found {count} matches (lịch + live) on {target_url}")

        urls = []
        for i in range(count):
            href = await matches.nth(i).locator("a.eventRowLink").get_attribute("href")
            if href:
                urls.append("https://www.flashscore.com" + href if not href.startswith("http") else href)
        return urls
    except Exception as e:
        print(f"⚠️ Fetch error {target_url}: {e}")
        return []

# ==================================================
# Filter theo yêu cầu của bạn
# ==================================================
def is_desired_match(data: dict) -> bool:
    if not data:
        return False
    sport = data["sport"]
    league = data["league"].lower().strip()
    home = data["home_team"].lower()
    away = data["away_team"].lower()

    if sport == "football":
        norm = league.replace("uefa ", "").replace("europe ", "").strip()
        if "champions league" in norm:
            key = "champions league"
        elif "europa league" in norm:
            key = "europa league"
        elif "conference league" in norm:
            key = "conference league"
        else:
            key = league

        if key in LEAGUE_TEAMS:
            teams_list = LEAGUE_TEAMS[key]
            if teams_list is None:
                return True
            return any(t in home or t in away for t in teams_list)
        return False

    elif sport == "tennis":
        l = league.lower()
        keywords = ["atp", "grand slam", "wimbledon", "us open", "french open",
                    "australian open", "roland garros"]
        return any(k in l for k in keywords)
    return False

# ==================================================
# Save JSON
# ==================================================
def save_flashscore(results):
    with open("flashscore.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved {len(results)} trận đấu → flashscore.json (có lịch + kênh livestream)")

# ==================================================
# Main (chạy 1 lần cho GitHub Actions)
# ==================================================
async def main():
    async with Stealth().use_async(async_playwright()) as p:
        async def start_browser():
            browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(timezone_id="UTC", locale="en-US")
            await context.route("**/*", lambda route, req: route.abort() if req.resource_type == "image" else route.continue_())
            page = await context.new_page()
            return browser, context, page

        browser, context, page = await start_browser()
        print(f"🚀 Bắt đầu scrape lịch trận đấu lúc {datetime.now(timezone.utc).isoformat()}")

        results = []

        # ===================== FOOTBALL - LỊCH TRẬN =====================
        print("⚽ Scraping Football schedule (today + upcoming)...")
        football_urls = await fetch_match_urls(page, "https://www.flashscore.com/football/")
        for i, url in enumerate(football_urls, 1):
            detail_page = await context.new_page()
            try:
                await detail_page.goto(url, wait_until="networkidle")
                await detail_page.wait_for_selector(".duelParticipant__container", timeout=15000)
                data = await extract_match_detail(detail_page)
                if data and is_desired_match(data):
                    results.append(data)
                    print(f"✓ FOOTBALL {data['home_team']} vs {data['away_team']} | {data['status']} | Kênh: {data['tv_channels'][0]}")
            finally:
                await detail_page.close()

        # ===================== TENNIS - LỊCH TRẬN =====================
        print("🎾 Scraping Tennis schedule (ATP + Grand Slam)...")
        tennis_urls = await fetch_match_urls(page, "https://www.flashscore.com/tennis/")
        for i, url in enumerate(tennis_urls, 1):
            detail_page = await context.new_page()
            try:
                await detail_page.goto(url, wait_until="networkidle")
                await detail_page.wait_for_selector(".duelParticipant__container", timeout=15000)
                data = await extract_match_detail(detail_page)
                if data and is_desired_match(data):
                    results.append(data)
                    print(f"✓ TENNIS {data['home_team']} vs {data['away_team']} | {data['status']}")
            finally:
                await detail_page.close()

        save_flashscore(results)
        await browser.close()
        print("✅ Hoàn thành! GitHub Actions sẽ tự commit flashscore.json")

if __name__ == "__main__":
    asyncio.run(main())
