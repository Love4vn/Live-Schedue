# File: livesportsontv.py
# Fixed: better logging, tennis support, time parsing with AM/PM, Vietnam time

import asyncio
import json
import re
from datetime import datetime
import zoneinfo
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# Timezone setup
UK_TZ = zoneinfo.ZoneInfo("Europe/London")
VIETNAM_TZ = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}

# ------------------------------------------------------------
# Helper for friendly matches
# ------------------------------------------------------------
EUROPEAN_COUNTRIES = {
    "albania", "andorra", "armenia", "austria", "azerbaijan", "belarus", "belgium",
    "bosnia and herzegovina", "bulgaria", "croatia", "cyprus", "czech republic",
    "denmark", "england", "estonia", "faroe islands", "finland", "france", "georgia",
    "germany", "gibraltar", "greece", "hungary", "iceland", "israel", "italy",
    "kazakhstan", "kosovo", "latvia", "liechtenstein", "lithuania", "luxembourg",
    "malta", "moldova", "monaco", "montenegro", "netherlands", "north macedonia",
    "northern ireland", "norway", "poland", "portugal", "republic of ireland",
    "romania", "russia", "san marino", "scotland", "serbia", "slovakia", "slovenia",
    "spain", "sweden", "switzerland", "turkey", "ukraine", "wales"
}

AMERICAS_TEAMS = {"argentina", "brazil"}
ASIA_TEAMS = {"japan", "south korea"}

def is_european_team(team: str) -> bool:
    t = team.lower()
    return any(c in t for c in EUROPEAN_COUNTRIES)

def is_americas_team(team: str) -> bool:
    t = team.lower()
    return any(c in t for c in AMERICAS_TEAMS)

def is_asia_team(team: str) -> bool:
    t = team.lower()
    return any(c in t for c in ASIA_TEAMS)

def include_friendly_match(home: str, away: str) -> bool:
    return (is_european_team(home) or is_european_team(away) or
            is_americas_team(home) or is_americas_team(away) or
            is_asia_team(home) or is_asia_team(away))

def parse_time_with_ampm(time_str: str) -> tuple[int, int]:
    """Convert time string like '10:00 PM' to 24h hour and minute."""
    time_str = time_str.strip().upper()
    # Handle possible absence of space, e.g., "10:00PM"
    if ' ' not in time_str and ('AM' in time_str or 'PM' in time_str):
        if 'AM' in time_str:
            time_str = time_str.replace('AM', ' AM')
        elif 'PM' in time_str:
            time_str = time_str.replace('PM', ' PM')
    parts = time_str.split()
    if len(parts) == 2:
        time_part, meridiem = parts
    else:
        time_part = parts[0]
        meridiem = None
    hour_min = time_part.split(':')
    if len(hour_min) < 2:
        raise ValueError(f"Invalid time format: {time_str}")
    hour = int(hour_min[0])
    minute = int(hour_min[1])
    if meridiem:
        if meridiem == 'PM' and hour != 12:
            hour += 12
        elif meridiem == 'AM' and hour == 12:
            hour = 0
    return hour, minute

# ------------------------------------------------------------
# Main scraping
# ------------------------------------------------------------
async def scrape_league_schedules():
    leagues_config = {
        # Club football
        "Premier League": {
            "url": "https://www.livesportsontv.com/league/premier-league",
            "teams": {"arsenal", "aston villa", "bournemouth", "brentford", "brighton",
                      "chelsea", "crystal palace", "everton", "fulham", "leeds united",
                      "liverpool", "manchester city", "manchester united", "newcastle",
                      "nottingham forest", "sunderland", "tottenham hotspur",
                      "west ham united", "wolverhampton"}
        },
        "Serie A": {
            "url": "https://www.livesportsontv.com/league/serie-a",
            "teams": {"inter milan", "ac milan", "napoli", "juventus", "roma",
                      "atalanta", "lazio"}
        },
        "La Liga": {
            "url": "https://www.livesportsontv.com/league/la-liga",
            "teams": {"barcelona", "real madrid", "atlético"}
        },
        "Bundesliga": {
            "url": "https://www.livesportsontv.com/league/bundesliga-5",
            "teams": {"bayern", "borussia dortmund", "bayer leverkusen"}
        },
        "Ligue 1": {
            "url": "https://www.livesportsontv.com/league/ligue-1-3",
            "teams": {"psg", "olympique marseille"}
        },
        "UEFA Champions League": {
            "url": "https://www.livesportsontv.com/league/uefa-champions-league",
            "teams": None
        },
        "UEFA Europa League": {
            "url": "https://www.livesportsontv.com/league/uefa-europa-league",
            "teams": None
        },
        "UEFA Europa Conference League": {
            "url": "https://www.livesportsontv.com/league/uefa-conference-league",
            "teams": None
        },
        "UEFA European Championship": {
            "url": "https://www.livesportsontv.com/league/uefa-european-championship",
            "teams": None
        },
        "FIFA World Cup": {
            "url": "https://www.livesportsontv.com/league/fifa-world-cup",
            "teams": None
        },
        "International Friendlies": {
            "url": "https://www.livesportsontv.com/league/friendly",
            "teams": None,
            "custom_filter": include_friendly_match
        },
        # Tennis
        "Tennis (ATP)": {
            "url": "https://www.livesportsontv.com/league/atp",
            "teams": None,
            "is_tennis": True
        },
        "Tennis (WTA)": {
            "url": "https://www.livesportsontv.com/league/wta",
            "teams": None,
            "is_tennis": True
        },
        "Australian Open": {
            "url": "https://www.livesportsontv.com/league/australian-open",
            "teams": None,
            "is_tennis": True
        },
        "French Open": {
            "url": "https://www.livesportsontv.com/league/french-open",
            "teams": None,
            "is_tennis": True
        },
        "Wimbledon": {
            "url": "https://www.livesportsontv.com/league/wimbledon",
            "teams": None,
            "is_tennis": True
        },
        "US Open": {
            "url": "https://www.livesportsontv.com/league/us-open",
            "teams": None,
            "is_tennis": True
        }
    }

    all_games = []
    now_uk = datetime.now(UK_TZ)
    target_day_uk = str(now_uk.day)
    target_month_uk = now_uk.strftime("%b").lower()
    current_year = now_uk.year

    async with async_playwright() as p:
        print("🚀 Starting browser...")
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        page.set_default_navigation_timeout(120000)
        page.set_default_timeout(60000)

        for league_name, config in leagues_config.items():
            url = config["url"]
            team_filter = config.get("teams")
            custom_filter = config.get("custom_filter")
            is_tennis = config.get("is_tennis", False)
            print(f"\n--- {league_name}: {url} ---")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=120000)
            except Exception as e:
                print(f"   ❌ Failed to load: {e}")
                continue

            # Scroll
            for _ in range(4):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            rows = soup.find_all('div', class_='event--wrapp')
            print(f"   Found {len(rows)} events.")

            added = 0
            for row in rows:
                try:
                    # Date extraction
                    date_div = row.find('div', class_='event__info--date')
                    if not date_div:
                        continue
                    day_tag = date_div.find('b')
                    month_tag = date_div.find('span')
                    if not day_tag or not month_tag:
                        continue
                    game_day = day_tag.get_text(strip=True)
                    game_month = month_tag.get_text(strip=True).lower()

                    if game_day != target_day_uk or game_month != target_month_uk:
                        continue

                    # Time parsing (handle AM/PM)
                    time_tag = row.find('time')
                    if not time_tag:
                        continue
                    time_str = time_tag.get_text(strip=True)
                    try:
                        hour, minute = parse_time_with_ampm(time_str)
                    except Exception as e:
                        print(f"   Time parse error: {e} for '{time_str}'")
                        continue

                    # Build UK datetime
                    month_num = MONTH_MAP.get(game_month, 1)
                    uk_dt = datetime(current_year, month_num, int(game_day), hour, minute)
                    uk_dt = uk_dt.replace(tzinfo=UK_TZ)
                    vn_dt = uk_dt.astimezone(VIETNAM_TZ)

                    # Get matchup text
                    if is_tennis:
                        # Tennis: the event title is usually inside an <a> or <span>
                        title_elem = row.find('a', class_='event__title')
                        if not title_elem:
                            title_elem = row.find('div', class_='event__title')
                        matchup = title_elem.get_text(strip=True) if title_elem else "Tennis Match"
                    else:
                        home_elem = row.find('div', class_=lambda c: c and 'event__participant--home' in c)
                        away_elem = row.find('div', class_=lambda c: c and 'event__participant--away' in c)
                        home = home_elem.get_text(strip=True) if home_elem else "Unknown"
                        away = away_elem.get_text(strip=True) if away_elem else "Unknown"
                        matchup = f"{away} @ {home}"
                        if home == "Unknown" and away == "Unknown":
                            # Fallback to title if available
                            title_elem = row.find('a', class_='event__title')
                            if title_elem:
                                matchup = title_elem.get_text(strip=True)

                    # Apply filters
                    if team_filter is not None:
                        if not any(t.lower() in matchup.lower() for t in team_filter):
                            continue
                    if custom_filter is not None:
                        # For friendlies, we need home/away names; if not available, skip
                        if home_elem and away_elem:
                            if not custom_filter(home, away):
                                continue
                        else:
                            continue

                    # Channels
                    channels = []
                    channel_list = row.find('ul', class_='event__tags')
                    if channel_list:
                        for link in channel_list.find_all('a'):
                            if aria := link.get('aria-label'):
                                channels.append(aria.strip())

                    all_games.append({
                        "Date": vn_dt.strftime("%Y-%m-%d"),
                        "Time": vn_dt.strftime("%H:%M"),
                        "League": league_name,
                        "Matchup": matchup,
                        "Services": channels
                    })
                    added += 1

                except Exception as e:
                    print(f"   Error processing row: {e}")
                    continue

            print(f"   → Added {added} matches")

        await browser.close()

    # Save
    filename = "schedule_livesportsontv.json"
    if all_games:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(all_games, f, indent=4, ensure_ascii=False)
        print(f"\n✅ {len(all_games)} matches saved to {filename}")
    else:
        print("⚠️ No matches today.")

if __name__ == "__main__":
    asyncio.run(scrape_league_schedules())
