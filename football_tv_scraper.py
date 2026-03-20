"""
football_tv_scraper.py
========================
Scrapes football match schedules from multiple sources:
- UK: Where's The Match (https://www.wheresthematch.com)
- US: WorldSoccerTalk (https://worldsoccertalk.com)
- FR: Matchs.tv (https://matchs.tv)

Outputs JSON files for each source and merged schedule.
"""

import asyncio
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Any

import pycountry
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ================== CONFIG ==================
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
UK_TIMEZONE = ZoneInfo("Europe/London")
US_TIMEZONE = ZoneInfo("America/New_York")
FR_TIMEZONE = ZoneInfo("Europe/Paris")

# Giới hạn 24h tới
NOW_TS = int(datetime.now(TIMEZONE).timestamp())
MAX_TS = NOW_TS + 86400

# Các giải đấu quan tâm
TARGET_LEAGUES = {
    "premier league", "serie a", "bundesliga", "la liga", "ligue 1",
    "uefa champions league", "uefa europa league", "uefa conference league"
}

# Hàm helper
def normalize(s: str) -> str:
    """Chuẩn hóa tên đội, giải đấu"""
    return re.sub(r'\s+', ' ', s.strip().lower())

def is_target_league(comp: str) -> bool:
    """Kiểm tra giải đấu có nằm trong danh sách quan tâm không"""
    comp_lower = normalize(comp)
    for target in TARGET_LEAGUES:
        if target in comp_lower:
            return True
    return False

def vn_time(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC")).astimezone(TIMEZONE)
    return dt.strftime("%d/%m %I:%M %p")

# ================== SCRAPERS ==================
async def scrape_wtm() -> List[Dict]:
    """Where's The Match (UK)"""
    url = "https://www.wheresthematch.com/live-football-on-tv/"
    fixtures = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=30000)
            await page.wait_for_selector('tr[itemscope][itemtype*="BroadcastEvent"]', timeout=10000)
            html = await page.content()
        except Exception as e:
            print(f"[WTM] Error: {e}")
            return []
        finally:
            await browser.close()

    soup = BeautifulSoup(html, 'lxml')
    rows = soup.select('tr[itemscope][itemtype*="BroadcastEvent"]')

    for row in rows:
        # Bỏ qua trận nữ
        if re.search(r"women'?s|womens|ladies", row.get_text(), re.I):
            continue

        # Đội nhà / khách
        team_links = row.select('td.fixture-details a[title]')
        if len(team_links) >= 2:
            home = team_links[0].get('title') or team_links[0].text.strip()
            away = team_links[-1].get('title') or team_links[-1].text.strip()
        else:
            fixture_cell = row.select_one('td.fixture-details')
            text = fixture_cell.get_text(strip=True) if fixture_cell else ""
            m = re.search(r'(.+?)\s+(?:v|vs|versus|–|-)\s+(.+)', text, re.I)
            if m:
                home, away = m.groups()
            else:
                continue
        home = home.strip()
        away = away.strip()

        # Thời gian
        meta = row.select_one('td.start-details meta[itemprop="startDate"]')
        if not meta or not meta.get('content'):
            continue
        iso = meta['content']
        if iso.endswith('Z'):
            iso = iso.replace('Z', '+00:00')
        try:
            dt = datetime.fromisoformat(iso)
            kick_utc = int(dt.timestamp())
        except:
            continue

        if not (NOW_TS <= kick_utc <= MAX_TS):
            continue

        # Giải đấu
        comp_elem = row.select_one('td.competition-name span')
        comp = comp_elem.text.strip() if comp_elem else ""
        if not is_target_league(comp):
            continue

        # Kênh
        channels = set()
        imgs = row.select('td.channel-details img')
        for img in imgs:
            alt = img.get('alt', '').strip()
            title = img.get('title', '').strip()
            name = alt or title
            if name:
                name = re.sub(r'\s+logo$', '', name, flags=re.I).strip()
                channels.add(name)
        chan_cell = row.select_one('td.channel-details')
        if chan_cell:
            text = chan_cell.get_text(separator=' ', strip=True)
            if text:
                for part in re.split(r'[,;]', text):
                    part = part.strip()
                    if part and not any(x in part.lower() for x in ['logo', 'image']):
                        channels.add(part)

        fixtures.append({
            "source": "wheresthematch",
            "country": "UK",
            "match": f"{home} vs {away}",
            "kick_utc": kick_utc,
            "time_vn": vn_time(kick_utc),
            "league": comp,
            "channels": list(channels)
        })

    return fixtures

async def scrape_worldsoccertalk() -> List[Dict]:
    """WorldSoccerTalk (US)"""
    url = "https://worldsoccertalk.com/tv-schedule/"
    fixtures = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=30000)
            # Chờ các element xuất hiện
            await page.wait_for_selector('div.flex.flex-col.w-full > div', timeout=10000)
            html = await page.content()
        except Exception as e:
            print(f"[WST] Error: {e}")
            return []
        finally:
            await browser.close()

    soup = BeautifulSoup(html, 'lxml')
    date_groups = soup.select('div.flex.flex-col.w-full > div')
    date_selector = "h3.text-stvsDate"
    match_row_selector = "li.border-stvsMatchBorderColor"
    hour_selector = ".text-stvsMatchHour"
    title_selector = ".text-stvsMatchTitle"
    provider_selector = ".text-stvsProviderLink a.hidden.md\\:inline-block"
    provider_fallback = ".text-stvsProviderLink a"

    for group in date_groups:
        date_elem = group.select_one(date_selector)
        if not date_elem:
            continue
        date_str = date_elem.get_text(strip=True)
        # Chuyển đổi date_str thành datetime
        # Định dạng: "Monday, March 16, 2026"
        try:
            dt_et = datetime.strptime(date_str, "%A, %B %d, %Y")
            dt_et = dt_et.replace(tzinfo=US_TIMEZONE)
        except:
            continue

        for row in group.select(match_row_selector):
            # Thời gian
            time_elem = row.select_one(hour_selector)
            if not time_elem:
                continue
            time_str = time_elem.get_text(strip=True).replace(" ET", "")
            try:
                # Định dạng: "7:30 PM" hoặc "7:30pm"
                time_obj = datetime.strptime(time_str, "%I:%M %p").time()
            except:
                try:
                    time_obj = datetime.strptime(time_str, "%I:%M%p").time()
                except:
                    continue
            dt_et_full = datetime.combine(dt_et.date(), time_obj, tzinfo=US_TIMEZONE)
            kick_utc = int(dt_et_full.astimezone(ZoneInfo("UTC")).timestamp())
            if not (NOW_TS <= kick_utc <= MAX_TS):
                continue

            # Teams and competition
            title_elem = row.select_one(title_selector)
            if not title_elem:
                continue
            title = title_elem.get_text(strip=True)
            # Title format: "Team A vs Team B (Competition)"
            match = title.split('(')[0].strip()
            comp = title.split('(')[-1].strip(')') if '(' in title else ""
            if not is_target_league(comp):
                continue

            # Channels
            channels = []
            providers = row.select(provider_selector)
            if not providers:
                providers = row.select(provider_fallback)
            for p in providers:
                ch = p.get_text(strip=True)
                if ch:
                    channels.append(ch)

            fixtures.append({
                "source": "worldsoccertalk",
                "country": "US",
                "match": match,
                "kick_utc": kick_utc,
                "time_vn": vn_time(kick_utc),
                "league": comp,
                "channels": channels
            })

    return fixtures

async def scrape_matchstv() -> List[Dict]:
    """Matchs.tv (FR)"""
    # Trang matchs.tv không có tổng hợp lịch tất cả các trận, cần tìm theo đội.
    # Nhưng chúng ta có thể lấy từ trang chủ: https://matchs.tv/programme-tv/
    url = "https://matchs.tv/programme-tv/"
    fixtures = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=30000)
            await page.wait_for_selector('table.programme-tv.fixtures', timeout=10000)
            html = await page.content()
        except Exception as e:
            print(f"[MatchsTV] Error: {e}")
            return []
        finally:
            await browser.close()

    soup = BeautifulSoup(html, 'lxml')
    rows = soup.select('table.programme-tv.fixtures tr')
    current_date = None
    current_naive_date = None
    for row in rows:
        # Xử lý header ngày
        date_header = row.select_one('h3 a')
        if date_header:
            date_text = date_header.get_text(strip=True)
            # Định dạng: "samedi 7 février"
            try:
                # Parse ngày tháng Pháp
                parts = date_text.split()
                if len(parts) >= 3:
                    day_num = int(parts[1])
                    month_map = {
                        'janvier': 1, 'février': 2, 'mars': 3, 'avril': 4, 'mai': 5, 'juin': 6,
                        'juillet': 7, 'août': 8, 'septembre': 9, 'octobre': 10, 'novembre': 11, 'décembre': 12
                    }
                    month_str = parts[2].lower()
                    month = month_map.get(month_str)
                    if month:
                        current_year = datetime.now().year
                        current_date = datetime(current_year, month, day_num)
                        current_naive_date = current_date.date()
            except:
                pass
            continue

        # Xử lý dòng trận đấu
        time_el = row.select_one('td.date')
        if not time_el:
            continue
        time_str = time_el.get_text(strip=True).replace('h', ':')
        if not time_str:
            continue
        try:
            time_obj = datetime.strptime(time_str, "%H:%M").time()
        except:
            continue

        if current_naive_date is None:
            continue
        dt_paris = datetime.combine(current_naive_date, time_obj, tzinfo=FR_TIMEZONE)
        kick_utc = int(dt_paris.astimezone(ZoneInfo("UTC")).timestamp())
        if not (NOW_TS <= kick_utc <= MAX_TS):
            continue

        # Đội bóng và giải
        fixture_el = row.select_one('td.fixture h4 a')
        if not fixture_el:
            continue
        fixture_text = fixture_el.get_text(strip=True)
        # Định dạng: "Paris Saint-Germain - Olympique de Marseille"
        if ' - ' in fixture_text:
            home, away = fixture_text.split(' - ', 1)
        else:
            continue

        comp_el = row.select_one('td.fixture .competitions')
        comp = comp_el.get_text(strip=True) if comp_el else ""
        if not is_target_league(comp):
            continue

        # Kênh
        channels = []
        channel_imgs = row.select('td.channel img')
        for img in channel_imgs:
            title = img.get('title', '').strip()
            if title:
                channels.append(title)

        fixtures.append({
            "source": "matchstv",
            "country": "FR",
            "match": f"{home} vs {away}",
            "kick_utc": kick_utc,
            "time_vn": vn_time(kick_utc),
            "league": comp,
            "channels": channels
        })

    return fixtures

# ================== MAIN ==================
async def main():
    print("🔄 Bắt đầu scrape lịch từ 3 nguồn...")
    results = {}

    print("📡 Scraping Where's The Match (UK)...")
    wtm = await scrape_wtm()
    results["wheresthematch"] = wtm
    with open("schedule_uk.json", "w", encoding="utf-8") as f:
        json.dump(wtm, f, indent=2, ensure_ascii=False)
    print(f"   ✅ {len(wtm)} trận")

    print("📡 Scraping WorldSoccerTalk (US)...")
    wst = await scrape_worldsoccertalk()
    results["worldsoccertalk"] = wst
    with open("schedule_us.json", "w", encoding="utf-8") as f:
        json.dump(wst, f, indent=2, ensure_ascii=False)
    print(f"   ✅ {len(wst)} trận")

    print("📡 Scraping Matchs.tv (FR)...")
    mtv = await scrape_matchstv()
    results["matchstv"] = mtv
    with open("schedule_fr.json", "w", encoding="utf-8") as f:
        json.dump(mtv, f, indent=2, ensure_ascii=False)
    print(f"   ✅ {len(mtv)} trận")

    # Merge tất cả vào một danh sách
    all_games = wtm + wst + mtv
    # Loại bỏ trùng lặp dựa trên (match, kick_utc)
    unique = {}
    for g in all_games:
        key = f"{g['match']}|{g['kick_utc']}"
        if key not in unique:
            unique[key] = g
        else:
            # Gộp kênh nếu có
            existing = unique[key]
            existing['channels'] = list(set(existing['channels'] + g['channels']))
    merged = list(unique.values())
    merged.sort(key=lambda x: x['kick_utc'])

    with open("schedule_merged.json", "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Tổng cộng {len(merged)} trận duy nhất trong 24h tới.")

if __name__ == "__main__":
    asyncio.run(main())
