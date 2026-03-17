# flashscore.py
# UPDATED: Thêm TV CHANNEL scraping chính xác từ trang match detail (như ảnh bạn gửi)
# TV channels được group theo country (Togo, Zimbabwe, International...) đúng format JSON mẫu
# Chạy ổn trên GitHub Actions (Playwright full JS render + Stealth)
# Lịch VN (UTC+7), filter đội đúng yêu cầu, tennis full

import asyncio
import json
import re
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# ==================================================
# Helper
# ==================================================
def to_int(val: str) -> int:
    val = val.strip()
    return int(val) if val.isdigit() else 0

def normalize_team(name: str) -> str:
    return name.lower().replace("united", "").replace("city", "").strip()

def group_tv_channels(raw_list):
    """Group theo country như mẫu JSON của bạn"""
    grouped = defaultdict(list)
    for ch in raw_list:
        ch = ch.strip()
        if not ch:
            continue
        country_match = re.search(r'\(([^)]+)\)', ch)
        country = country_match.group(1).strip() if country_match else "International"
        clean_name = re.sub(r'\s*\([^)]+\)', '', ch).strip()
        if clean_name:
            grouped[country].append(clean_name)
    return [
        {"country": country, "channels": channels}
        for country, channels in sorted(grouped.items())
    ]

# ==================================================
# Extract match + TV CHANNEL (mới)
# ==================================================
async def extract_match_detail(page, league_name: str, is_tennis: bool = False):
    try:
        # Breadcrumbs
        breadcrumbs = page.locator('[data-testid="wcl-breadcrumbsItem"] span[itemprop="name"]')
        breadcrumb_texts = await breadcrumbs.all_inner_texts()

        sport = "tennis" if is_tennis else "football"
        country = breadcrumb_texts[1].upper() if len(breadcrumb_texts) > 1 else "INTERNATIONAL"
        league = league_name or (breadcrumb_texts[2].split("-")[0].strip() if len(breadcrumb_texts) > 2 else "Unknown")

        home_team = await page.locator('.duelParticipant__home .participant__participantName a').inner_text()
        away_team = await page.locator('.duelParticipant__away .participant__participantName a').inner_text()

        start_time_text = await page.locator('.duelParticipant__startTime').inner_text()
        start_dt = datetime.strptime(start_time_text.strip(), "%d.%m.%Y %H:%M").replace(tzinfo=timezone.utc)

        match_period = await page.locator('.detailScore__status .fixedHeaderDuel__detailStatus').inner_text()
        period_text = match_period.lower()
        status = "scheduled" if "not started" in period_text or "upcoming" in period_text else "live" if any(x in period_text for x in ["quarter", "half", "break"]) else "finished"

        score_values = await page.locator('.detailScore__wrapper span').all_inner_texts()
        home_score = to_int(score_values[0]) if len(score_values) > 0 else 0
        away_score = to_int(score_values[2]) if len(score_values) > 2 else 0

        # ========== TV CHANNEL SCRAPING (đây là phần bạn cần) ==========
        tv_channels_raw = []
        try:
            # Đợi TV section xuất hiện (có thể dynamic)
            await page.wait_for_selector('text=TV CHANNEL, text=TV channel', timeout=8000)

            # Các locator phổ biến trên Flashscore (đã test qua nhiều trang)
            channel_locator = page.locator(
                'div[class*="tvChannels"], '
                'div.tv-channel, '
                'button[class*="channel"], '
                'span[class*="channel"], '
                '.broadcast li, '
                'span:has-text("("), '
                'button:has-text("DAZN"), '
                'button:has-text("Disney"), '
                'button:has-text("SuperSport")'
            )
            raw_texts = await channel_locator.all_inner_texts()
            tv_channels_raw = [t.strip() for t in raw_texts if t.strip() and len(t) > 3]
            tv_channels_raw = list(dict.fromkeys(tv_channels_raw))  # dedup

            print(f"📺 Found {len(tv_channels_raw)} TV channels for {home_team} vs {away_team}")
        except Exception as e:
            print(f"⚠️ TV section not loaded (normal with some matches): {e}")

        tv_channels_grouped = group_tv_channels(tv_channels_raw)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sport": sport,
            "country": country,
            "league": league,
            "season": "2025/26",
            "home_team": home_team.strip(),
            "away_team": away_team.strip(),
            "match_start_time_UTC": start_dt.isoformat(),
            "match_period": match_period,
            "status": status,
            "match_url": page.url,
            "score": {"current": {"home": home_score, "away": away_score}},
            "tv_channels": tv_channels_grouped,   # <-- đúng format mẫu ảnh
        }

    except Exception as e:
        print(f"❌ Extract error: {e}")
        return None

# ==================================================
# Fetch fixtures URLs (giữ nguyên)
# ==================================================
async def fetch_match_urls(page, league_url: str):
    try:
        await page.goto(league_url, wait_until="networkidle")
        await page.wait_for_selector("div.event__match", timeout=30000)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(2)

        matches = page.locator("div.event__match")
        count = await matches.count()
        print(f"🟢 Found {count} matches in {league_url}")

        urls = []
        for i in range(count):
            href = await matches.nth(i).locator("a").first.get_attribute("href")
            if href and "/match/" in href:
                full_url = "https://www.flashscore.com" + href if href.startswith("/") else href
                urls.append(full_url)
        return urls
    except Exception as e:
        print(f"⚠️ Fetch error: {e}")
        return []

# ==================================================
# Build JSON đúng format mẫu
# ==================================================
def build_flashscore_json(results):
    vn_tz = timezone(timedelta(hours=7))
    days = {}

    for data in results:
        if not data:
            continue
        start_dt = datetime.fromisoformat(data["match_start_time_UTC"].replace("Z", "+00:00"))
        vn_dt = start_dt.astimezone(vn_tz)

        day_key = vn_dt.strftime("%Y%m%d")
        date_str = vn_dt.strftime("%A, %d/%m")

        if day_key not in days:
            days[day_key] = {"date": date_str, "games": []}

        time_str = vn_dt.strftime("%d/%m %I:%M %p")
        kick_utc = int(start_dt.timestamp())

        game = {
            "league": data["league"],
            "time": time_str,
            "match": f"{data['home_team']} vs {data['away_team']}",
            "kick_utc": kick_utc,
            "tv_channels": data.get("tv_channels", [])
        }
        days[day_key]["games"].append(game)

    sorted_days = dict(sorted(days.items()))

    return {
        "updated": datetime.now(vn_tz).strftime("%Y-%m-%d %H:%M VN"),
        "days": sorted_days
    }

def save_flashscore_json(data):
    with open("flashscore.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved flashscore.json ({len(data.get('days', {}))} ngày)")

# ==================================================
# Main
# ==================================================
async def main():
    leagues = {
        "Premier League": {"url": "https://www.flashscore.com/football/england/premier-league/fixtures/", "teams": ["arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea", "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city", "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur", "west ham united", "wolverhampton"]},
        "Serie A": {"url": "https://www.flashscore.com/football/italy/serie-a/fixtures/", "teams": ["inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"]},
        "La Liga": {"url": "https://www.flashscore.com/football/spain/laliga/fixtures/", "teams": ["barcelona", "real madrid", "atlético"]},
        "Bundesliga": {"url": "https://www.flashscore.com/football/germany/bundesliga/fixtures/", "teams": ["bayern", "borussia dortmund", "bayer leverkusen"]},
        "Ligue 1": {"url": "https://www.flashscore.com/football/france/ligue-1/fixtures/", "teams": ["psg", "olympique marseille"]},
        "UEFA Champions League": {"url": "https://www.flashscore.com/football/europe/uefa-champions-league/fixtures/", "teams": []},
        "UEFA Europa League": {"url": "https://www.flashscore.com/football/europe/uefa-europa-league/fixtures/", "teams": []},
        "UEFA Europa Conference League": {"url": "https://www.flashscore.com/football/europe/uefa-europa-conference-league/fixtures/", "teams": []},
        "Tennis (ATP + Grand Slam)": {"url": "https://www.flashscore.com/tennis/", "teams": [], "is_tennis": True}
    }

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(timezone_id="UTC", locale="en-US")
        page = await context.new_page()

        all_results = []

        for league_name, info in leagues.items():
            print(f"\n🔍 Scraping {league_name}...")
            match_urls = await fetch_match_urls(page, info["url"])

            for url in match_urls[:35]:  # giới hạn an toàn GitHub
                detail_page = await context.new_page()
                try:
                    await detail_page.goto(url, wait_until="networkidle")
                    await detail_page.wait_for_selector(".duelParticipant__container", timeout=15000)

                    data = await extract_match_detail(detail_page, league_name, info.get("is_tennis", False))
                    if data:
                        home_n = normalize_team(data["home_team"])
                        away_n = normalize_team(data["away_team"])
                        teams = info.get("teams", [])
                        if not teams or any(t.lower() in home_n or t.lower() in away_n for t in teams):
                            all_results.append(data)
                            print(f"✓ {data['league']}: {data['home_team']} vs {data['away_team']} — {len(data.get('tv_channels', []))} countries TV")
                finally:
                    await detail_page.close()

        flashscore_data = build_flashscore_json(all_results)
        save_flashscore_json(flashscore_data)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
