```python
import asyncio
import json
import re
import unicodedata
import urllib.request
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

import pycountry
import requests
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession


TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")

M3U_LIST_FILE = "M3U_list.txt"
SCHEDULE_FILE = "schedule.json"
LIVE_M3U = "live_schedule.m3u"


# =========================================================
# HELPERS
# =========================================================

def normalize(text):
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(text.split())


def vn_time(ts):
    dt = datetime.fromtimestamp(ts, tz=ZoneInfo("UTC")).astimezone(TIMEZONE)
    return dt.strftime("%d/%m %H:%M")


def fetch_text(url):
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        return r.text
    except:
        return ""


def is_healthy(url):

    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.getcode() < 400
    except:
        return False


def channel_match(name, channel):

    a = normalize(name)
    b = normalize(channel)

    if a in b or b in a:
        return True

    a = a.replace("sports", "sport")
    b = b.replace("sports", "sport")

    return a in b


# =========================================================
# SOFASCORE
# =========================================================

async def get_channel_name(session, cid):

    url = f"https://api.sofascore.com/api/v1/tv/channel/{cid}/schedule"

    try:
        r = await session.get(url, impersonate="chrome120", timeout=10)
        if r.status_code == 200:
            return r.json().get("channel", {}).get("name")
    except:
        pass

    return None


async def get_tv_data(session, event_id):

    url = f"https://api.sofascore.com/api/v1/tv/event/{event_id}/country-channels"

    try:

        r = await session.get(url, impersonate="chrome120", timeout=15)

        if r.status_code != 200:
            return []

        data = r.json().get("countryChannels", {})

        broadcasters = []

        for code, cids in data.items():

            country = pycountry.countries.get(alpha_2=code)
            country_name = country.name if country else code

            names = await asyncio.gather(
                *[get_channel_name(session, cid) for cid in cids]
            )

            names = [n for n in names if n]

            if names:
                broadcasters.append({
                    "country": country_name,
                    "channels": list(set(names))
                })

        return broadcasters

    except:
        return []


async def fetch_event(session, event_id, sport, now_ts):

    url = f"https://api.sofascore.com/api/v1/event/{event_id}"

    try:

        r = await session.get(url, impersonate="chrome120", timeout=15)

        if r.status_code != 200:
            return None

        ev = r.json().get("event", {})

        start_ts = ev.get("startTimestamp")

        if not start_ts:
            return None

        if not (now_ts <= start_ts <= now_ts + 86400):
            return None

        tv = await get_tv_data(session, event_id)

        home = ev.get("homeTeam", {}).get("name", "")
        away = ev.get("awayTeam", {}).get("name", "")

        if sport == "tennis":

            league = "Tennis"
            match = f"{home} vs {away}"

        else:

            league_raw = ev.get("tournament", {}).get("name", "")

            league_lower = league_raw.lower()

            if "premier" in league_lower:
                league = "Premier League"
            elif "serie" in league_lower:
                league = "Serie A"
            elif "bundes" in league_lower:
                league = "Bundesliga"
            elif "liga" in league_lower:
                league = "La Liga"
            elif "ligue" in league_lower:
                league = "Ligue 1"
            elif "champions" in league_lower:
                league = "UEFA Champions League"
            elif "europa" in league_lower:
                league = "UEFA Europa League"
            else:
                return None

            match = f"{home} vs {away}"

        return {
            "league": league,
            "time": vn_time(start_ts),
            "match": match,
            "kick_utc": start_ts,
            "tv_channels": tv
        }

    except:
        return None


async def process_24h(session, sport):

    now = datetime.now(TIMEZONE)

    dates = [
        now.strftime("%Y-%m-%d"),
        (now + timedelta(days=1)).strftime("%Y-%m-%d")
    ]

    now_ts = int(now.timestamp())

    results = []

    for d in dates:

        url = f"https://www.sofascore.com/api/v1/sport/{sport}/scheduled-events/{d}"

        r = await session.get(url, impersonate="chrome120", timeout=30)

        if r.status_code != 200:
            continue

        events = r.json().get("events", [])

        tasks = [
            fetch_event(session, e["id"], sport, now_ts)
            for e in events
        ]

        out = await asyncio.gather(*tasks)

        results.extend([x for x in out if x])

    return results


# =========================================================
# WHERES THE MATCH
# =========================================================

def scrape_wtm():

    url = "https://www.wheresthematch.com/live-football-on-tv/"

    html = fetch_text(url)

    soup = BeautifulSoup(html, "html.parser")

    fixtures = []

    rows = soup.select("tr[itemscope]")

    for r in rows:

        fix = r.select_one(".fixture-details")

        if not fix:
            continue

        text = fix.get_text(" ", strip=True)

        m = re.search(r"(.+?)\s+v\s+(.+)", text)

        if not m:
            continue

        home = normalize(m.group(1))
        away = normalize(m.group(2))

        channels = []

        for img in r.select(".channel-details img"):
            name = img.get("alt", "").replace(" logo", "")
            if name:
                channels.append(name)

        fixtures.append({
            "home": home,
            "away": away,
            "channels": list(set(channels))
        })

    return fixtures


# =========================================================
# LIVESOCCERTV
# =========================================================

def scrape_livesoccertv():

    url = "https://www.livesoccertv.com/schedules/"

    html = fetch_text(url)

    soup = BeautifulSoup(html, "html.parser")

    fixtures = []

    rows = soup.select("tr.matchrow")

    for r in rows:

        teams = r.select_one(".match")

        if not teams:
            continue

        text = teams.get_text(" ", strip=True)

        m = re.search(r"(.+?)\s+vs\s+(.+)", text)

        if not m:
            continue

        home = normalize(m.group(1))
        away = normalize(m.group(2))

        channels = []

        for c in r.select(".channels a"):
            name = c.get_text(strip=True)
            if name:
                channels.append(name)

        fixtures.append({
            "home": home,
            "away": away,
            "channels": list(set(channels))
        })

    return fixtures


# =========================================================
# M3U PARSER
# =========================================================

def parse_m3u(content):

    channels = []

    current = {}

    for line in content.splitlines():

        line = line.strip()

        if line.startswith("#EXTINF"):

            name = line.split(",", 1)[-1]

            current = {"name": name}

        elif line.startswith("http"):

            current["url"] = line
            channels.append(current)
            current = {}

    return channels


# =========================================================
# MAIN
# =========================================================

async def main():

    start = time.time()

    print("Fetching SofaScore...")

    all_games = []

    async with AsyncSession() as session:

        for sport in ["football", "tennis"]:

            g = await process_24h(session, sport)

            all_games.extend(g)

            await asyncio.sleep(2)

    print("Fetching WTM...")

    wtm = scrape_wtm()

    wtm_map = {
        f["home"] + "|" + f["away"]: f["channels"]
        for f in wtm
    }

    print("Fetching LiveSoccerTV...")

    lstv = scrape_livesoccertv()

    lstv_map = {
        f["home"] + "|" + f["away"]: f["channels"]
        for f in lstv
    }

    for g in all_games:

        try:

            home = normalize(g["match"].split(" vs ")[0])
            away = normalize(g["match"].split(" vs ")[1])

            key = home + "|" + away

            if key in wtm_map:

                g["tv_channels"].append({
                    "country": "UK",
                    "channels": wtm_map[key]
                })

            if key in lstv_map:

                g["tv_channels"].append({
                    "country": "Global",
                    "channels": lstv_map[key]
                })

        except:
            continue

    with open(SCHEDULE_FILE, "w", encoding="utf8") as f:
        json.dump(all_games, f, indent=2, ensure_ascii=False)

    print("Loading M3U...")

    m3u_urls = [
        l.strip()
        for l in open(M3U_LIST_FILE)
        if l.startswith("http")
    ]

    all_channels = []

    with ThreadPoolExecutor(max_workers=20) as ex:

        futures = {
            ex.submit(fetch_text, url): url
            for url in m3u_urls
        }

        for f in as_completed(futures):

            content = f.result()

            chs = parse_m3u(content)

            all_channels.extend(chs)

    valid_channels = [
        ch for ch in all_channels
        if is_healthy(ch["url"])
    ]

    live_events = []

    for g in all_games:

        for tv in g["tv_channels"]:

            for ch_name in tv["channels"]:

                matches = [
                    ch for ch in valid_channels
                    if channel_match(ch_name, ch["name"])
                ]

                for ch in matches:

                    live_events.append({
                        "time": g["time"],
                        "match": g["match"],
                        "league": g["league"],
                        "url": ch["url"],
                        "channel": ch_name
                    })

    with open(LIVE_M3U, "w", encoding="utf8") as f:

        f.write("#EXTM3U\n")

        for ev in live_events:

            name = f'{ev["time"]} | {ev["match"]} ({ev["channel"]})'

            f.write(f'#EXTINF:-1 group-title="{ev["league"]}",{name}\n')

            f.write(ev["url"] + "\n")

    print("DONE")
    print("Matches:", len(all_games))
    print("Streams:", len(live_events))
    print("Time:", round(time.time() - start, 1), "sec")


if __name__ == "__main__":
    asyncio.run(main())
```
