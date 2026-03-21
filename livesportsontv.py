# File: livesportsontv.py
# Optimized for broader coverage including tennis and international football

import asyncio
import json
import re
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# ------------------------------------------------------------
# Helper functions for friendly match filtering
# ------------------------------------------------------------
EUROPEAN_COUNTRIES = {
    "albania", "andorra", "armenia", "austria", "azerbaijan", "belarus", "belgium",
    "bosnia and herzegovina", "bulgaria", "croatia", "cyprus", "czech republic",
    "denmark", "england", "estonia", "faroe islands", "finland", "france", "georgia",
    "germany", "gibraltar", "greece", "hungary", "iceland", "israel", "italy",
    "kazakhstan", "kosovo", "latvia", "liechtenstein", "lithuania", "luxembourg",
    "malta", "moldova", "montenegro", "netherlands", "north macedonia", "northern ireland",
    "norway", "poland", "portugal", "republic of ireland", "romania", "russia",
    "san marino", "scotland", "serbia", "slovakia", "slovenia", "spain", "sweden",
    "switzerland", "turkey", "ukraine", "wales"
}

AMERICAS_TEAMS = {"argentina", "brazil"}
ASIA_TEAMS = {"japan", "south korea"}

def is_european_team(team_name: str) -> bool:
    """Check if team name matches any European country."""
    team_lower = team_name.lower()
    for country in EUROPEAN_COUNTRIES:
        if country in team_lower:
            return True
    return False

def is_americas_team(team_name: str) -> bool:
    """Check if team is Argentina or Brazil."""
    team_lower = team_name.lower()
    return any(t in team_lower for t in AMERICAS_TEAMS)

def is_asia_team(team_name: str) -> bool:
    """Check if team is Japan or South Korea."""
    team_lower = team_name.lower()
    return any(t in team_lower for t in ASIA_TEAMS)

def include_friendly_match(home: str, away: str) -> bool:
    """
    Decide whether to include a friendly match based on the filter rules:
    - European teams: all (any European country involved)
    - Americas: only Argentina or Brazil
    - Asia: only Japan or South Korea
    """
    # If either team is European, include (all European teams)
    if is_european_team(home) or is_european_team(away):
        return True
    # If either team is Argentina or Brazil, include
    if is_americas_team(home) or is_americas_team(away):
        return True
    # If either team is Japan or South Korea, include
    if is_asia_team(home) or is_asia_team(away):
        return True
    return False

# ------------------------------------------------------------
# Main scraping function
# ------------------------------------------------------------
async def scrape_league_schedules():
    leagues_config = {
        # Existing club leagues (unchanged)
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
        "Tennis (ATP)": {
            "url": "https://www.livesportsontv.com/league/atp",
            "teams": None
        },

        # ----- New additions -----
        # Tennis: WTA
        "Tennis (WTA)": {
            "url": "https://www.livesportsontv.com/league/wta",
            "teams": None
        },
        # Grand Slams
        "Australian Open": {
            "url": "https://www.livesportsontv.com/league/australian-open",
            "teams": None
        },
        "French Open": {
            "url": "https://www.livesportsontv.com/league/french-open",
            "teams": None
        },
        "Wimbledon": {
            "url": "https://www.livesportsontv.com/league/wimbledon",
            "teams": None
        },
        "US Open": {
            "url": "https://www.livesportsontv.com/league/us-open",
            "teams": None
        },
        # International tournaments
        "UEFA European Championship": {
            "url": "https://www.livesportsontv.com/league/uefa-european-championship",
            "teams": None
        },
        "FIFA World Cup": {
            "url": "https://www.livesportsontv.com/league/fifa-world-cup",
            "teams": None
        },
        # International friendlies (special filter)
        "International Friendlies": {
            "url": "https://www.livesportsontv.com/league/friendly",
            "teams": None,                # filter handled separately
            "custom_filter": include_friendly_match
        }
    }

    all_games = []
    today = datetime.now()
    target_day = str(today.day)
    target_month = today.strftime("%b").lower()

    async with async_playwright() as p:
        print("🚀 Starting browser headless...")
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        page = await browser.new_page()

        # Sync timeouts (no await)
        page.set_default_navigation_timeout(120000)  # 120s
        page.set_default_timeout(60000)

        for league_name, config in leagues_config.items():
            url = config["url"]
            team_filter = config.get("teams")
            custom_filter = config.get("custom_filter")
            print(f"\n--- Scraping {league_name}: {url} ---")

            # Retry logic (2 attempts)
            success = False
            for attempt in range(2):
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=120000)
                    success = True
                    break
                except Exception as e:
                    print(f"   ⚠️ Attempt {attempt+1} failed: {e}")
                    if attempt == 1:
                        print(f"   ❌ Skipping {league_name}")
            if not success:
                continue

            # Scroll to load content
            for _ in range(4):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

            html_content = await page.content()
            soup = BeautifulSoup(html_content, 'html.parser')

            # Find all match blocks (same structure for football and tennis)
            game_rows = soup.find_all('div', class_='event--wrapp')
            print(f"  → Found {len(game_rows)} events. Filtering for today...")

            games_added = 0
            for row in game_rows:
                try:
                    # Date check
                    date_div = row.find('div', class_='event__info--date')
                    if not date_div:
                        continue
                    game_day = date_div.find('b').get_text(strip=True) if date_div.find('b') else ""
                    game_month = date_div.find('span').get_text(strip=True).lower() if date_div.find('span') else ""
                    if game_day != target_day or game_month != target_month:
                        continue

                    # Time
                    time_div = row.find('time')
                    event_time = time_div.get_text(strip=True) if time_div else "Time Not Found"

                    # Home / Away (participants)
                    home_elem = row.find('div', class_=lambda c: c and 'event__participant--home' in c)
                    away_elem = row.find('div', class_=lambda c: c and 'event__participant--away' in c)
                    home_team = home_elem.get_text(strip=True) if home_elem else "Unknown"
                    away_team = away_elem.get_text(strip=True) if away_elem else "Unknown"
                    matchup = f"{away_team} @ {home_team}"

                    # Apply team filter if defined (for club leagues)
                    if team_filter is not None:
                        if not any(t.lower() in home_team.lower() or t.lower() in away_team.lower() for t in team_filter):
                            continue

                    # Apply custom filter for friendlies
                    if custom_filter is not None:
                        if not custom_filter(home_team, away_team):
                            continue

                    # Channels (TV broadcasters)
                    channels = []
                    channel_list = row.find('ul', class_='event__tags')
                    if channel_list:
                        for link in channel_list.find_all('a'):
                            if aria := link.get('aria-label'):
                                channels.append(aria.strip())

                    all_games.append({
                        "Date": today.strftime("%Y-%m-%d"),
                        "Time": event_time,
                        "League": league_name,
                        "Matchup": matchup,
                        "Services": channels
                    })
                    games_added += 1

                except Exception as e:
                    # Skip any malformed rows
                    continue

            print(f"  → Added {games_added} matches for {league_name}")

        await browser.close()
        print("\n✅ Scraping completed!")

    # Save results to JSON
    filename = "schedule_livesportsontv.json"
    if all_games:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(all_games, f, indent=4, ensure_ascii=False)
        print(f"\n🎉 SUCCESS: {len(all_games)} matches found!")
        print(f"📁 File: {filename} (ready for commit)")
    else:
        print("⚠️ No matches scheduled for today.")

if __name__ == "__main__":
    asyncio.run(scrape_league_schedules())
