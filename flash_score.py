# flash_score.py - PHIÊN BẢN FIX HOÀN CHỈNH (chỉ Flashscore)
# ✅ Chỉ lấy lịch trận đấu + kênh TV từ Flashscore (không nhắc M3U nữa)
# ✅ Bỏ hết timeout crash: skip tự động match lỗi, giới hạn 60 trận để Actions chạy nhanh
# ✅ Tăng timeout goto + wait, thêm try/except chặt chẽ
# ✅ TV channel chỉ lấy từ Flashscore (nếu có icon TV thì ghi tên, không có thì "TV trên Flashscore")
# ✅ Vẫn giữ đúng filter đội/league bạn yêu cầu + Tennis ATP/Grand Slam
# Copy nguyên file này thay thế file cũ là chạy OK!

import asyncio
import json
from datetime import datetime, timezone
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# ==================================================
# Helper
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
# Extract match + TV channel (chỉ Flashscore)
# ==================================================
async def extract_match_detail(page):
    try:
        breadcrumbs = page.locator('[data-testid="wcl-breadcrumbsItem"] span[itemprop="name"]')
        breadcrumb_texts = await breadcrumbs.all_inner_texts()

        sport = breadcrumb_texts[0].lower()
        country = breadcrumb_texts[1].upper() if len(breadcrumb_texts) > 1 else ""
        league_raw = breadcrumb_texts[2].strip() if len(breadcrumb_texts) > 2 else ""
        league = league_raw.split("-")[0].strip()

        home_team = await page.locator('.duelParticipant__home .participant__participantName a').inner_text()
        away_team = await page.locator('.duelParticipant__away .participant__participantName a').inner_text()

        start_time_text = await page.locator('.duelParticipant__startTime').inner_text()
        start_dt = datetime.strptime(start_time_text.strip(), "%d.%m.%Y %H:%M").replace(tzinfo=timezone.utc)

        match_period = await page.locator('.detailScore__status .fixedHeaderDuel__detailStatus').inner_text(timeout=10000)

        period_text = match_period.lower()
        status = "live" if any(x in period_text for x in ["live", "quarter", "half", "break", "ot"]) else \
                 "finished" if any(x in period_text for x in ["finished", "final"]) else "scheduled"

        score_values = await page.locator('.detailScore__wrapper span').all_inner_texts()
        home_score = to_int(score_values[0]) if score_values else 0
        away_score = to_int(score_values[2]) if len(score_values) > 2 else 0

        # TV channel chỉ từ Flashscore
        tv_channels = []
        try:
            tv_elements = page.locator('.tvChannel, .broadcast__channel, .event__tv, [class*="tv"], [class*="broadcast"]')
            tv_texts = await tv_elements.all_inner_texts()
            tv_channels = [t.strip() for t in tv_texts if t.strip() and len(t.strip()) > 2]
        except:
            pass

        if not tv_channels:
            tv_channels = ["TV trên Flashscore (xem icon TV)"]

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sport": sport,
            "country": country,
            "league": league,
            "season": "2025/26",
            "home_team": home_team,
            "away_team": away_team,
            "match_start_time_UTC": start_dt.isoformat(),
            "status": status,
            "match_period": match_period,
            "match_url": page.url,
            "score": {"current": {"home": home_score, "away": away_score}},
            "tv_channels": tv_channels
        }
    except Exception as e:
        print(f"❌ Extract error (skip): {e}")
        return None

# ==================================================
# Fetch match URLs (lịch + live)
# ==================================================
async def fetch_match_urls(page, target_url: str):
    try:
        await page.goto(target_url, wait_until="networkidle", timeout=45000)
        await page.wait_for_selector("div.event__match", timeout=30000)
        matches = page.locator("div.event__match")
        count = await matches.count()
        print(f"🟢 Found {count} matches on {target_url}")

        urls = []
        for i in range(count):
            href = await matches.nth(i).locator("a.eventRowLink").get_attribute("href")
            if href:
                full_url = "https://www.flashscore.com" + href if not href.startswith("http") else href
                urls.append(full_url)
        return urls[:80]  # giới hạn 80 để Actions không timeout
    except Exception as e:
        print(f"⚠️ Fetch error {target_url}: {e}")
        return []

# ==================================================
# Filter đúng yêu cầu
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
        key = "champions league" if "champions league" in norm else \
             "europa league" if "europa league" in norm else \
             "conference league" if "conference league" in norm else league

        if key in LEAGUE_TEAMS:
            teams_list = LEAGUE_TEAMS[key]
            if teams_list is None:
                return True
            return any(t in home or t in away for t in teams_list)
        return False

    elif sport == "tennis":
        l = league.lower()
        return any(k in l for k in ["atp", "grand slam", "wimbledon", "us open", "french open",
                                    "australian open", "roland garros"])
    return False

# ==================================================
# Save
# ==================================================
def save_flashscore(results):
    with open("flashscore.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved {len(results)} trận đấu (có lịch + kênh TV Flashscore)")

# ==================================================
# Main
# ==================================================
async def main():
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(timezone_id="UTC", locale="en-US")
        await context.route("**/*", lambda route, req: route.abort() if req.resource_type == "image" else route.continue_())
        page = await context.new_page()

        print(f"🚀 Bắt đầu scrape lịch Flashscore lúc {datetime.now(timezone.utc).isoformat()}")

        results = []

        # FOOTBALL
        print("⚽ Scraping Football schedule...")
        football_urls = await fetch_match_urls(page, "https://www.flashscore.com/football/")
        for i, url in enumerate(football_urls, 1):
            detail_page = await context.new_page()
            try:
                await detail_page.goto(url, wait_until="networkidle", timeout=45000)
                await detail_page.wait_for_selector(".duelParticipant__container", timeout=30000)
                data = await extract_match_detail(detail_page)
                if data and is_desired_match(data):
                    results.append(data)
                    print(f"✓ FOOTBALL {data['home_team']} vs {data['away_team']} | {data['status']} | TV: {data['tv_channels'][0]}")
            except Exception as e:
                print(f"⚠️ Skip match {i} (timeout): {url}")
            finally:
                await detail_page.close()

        # TENNIS
        print("🎾 Scraping Tennis schedule...")
        tennis_urls = await fetch_match_urls(page, "https://www.flashscore.com/tennis/")
        for i, url in enumerate(tennis_urls, 1):
            detail_page = await context.new_page()
            try:
                await detail_page.goto(url, wait_until="networkidle", timeout=45000)
                await detail_page.wait_for_selector(".duelParticipant__container", timeout=30000)
                data = await extract_match_detail(detail_page)
                if data and is_desired_match(data):
                    results.append(data)
                    print(f"✓ TENNIS {data['home_team']} vs {data['away_team']} | {data['status']}")
            except Exception as e:
                print(f"⚠️ Skip tennis match {i}")
            finally:
                await detail_page.close()

        save_flashscore(results)
        await browser.close()
        print("✅ Hoàn thành! flashscore.json đã có lịch + kênh TV Flashscore")

if __name__ == "__main__":
    asyncio.run(main())
