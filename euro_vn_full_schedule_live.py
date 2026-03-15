"""
euro_vn_full_schedule_live.py
================================
BẢN HOÀN CHỈNH CUỐI CÙNG – LẤY TRẬN TRONG 24 GIỜ TỚI (từ lúc chạy)
- Bóng đá: CHỈ trận có đội trong list + chỉ các giải bạn muốn (Premier, Serie A, Bundesliga, La Liga, Ligue 1, UCL, UEL, Conference)
- Tennis: lấy tất cả
- Group-title chính xác: "Live Premier League", "Live Serie A", ...
- Tên trận: "DD/MM HH:MM | Arsenal vs Man City (Sky Sports Premier League)"
- Dedup URL triệt để + GIỮ NGUYÊN TẤT CẢ extra lines (#KODIPROP, #EXTHTTP, #EXTVLCOPT, #EXTGRP, #EXT-X-..., ...)
- Loại SD/low-res + kênh lỗi
- Sắp xếp theo giờ Việt Nam
"""

import asyncio
import json
import re
import unicodedata
import urllib.request
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote
import pycountry
from curl_cffi.requests import AsyncSession

# ================== CẤU HÌNH ==================
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
M3U_LIST_FILE = "M3U_list.txt"
SCHEDULE_FILE = "schedule.json"
LIVE_M3U = "live_schedule.m3u"

ALLOWED_TEAMS = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton", "bayern", "borussia dortmund", "bayer leverkusen",
    "inter milan", "ac milan", "napoli", "barcelona", "real madrid", "atlético", "psg",
    "olympique marseille"
}

# Từ khóa giải đấu (substring để tránh miss "LaLiga" hoặc "La Liga EA Sports")
ALLOWED_LEAGUE_KEYWORDS = [
    "premier league", "serie a", "bundesliga", "la liga", "ligue 1",
    "uefa champions league", "uefa europa league", "uefa europa conference league"
]

LEAGUE_GROUP_NAME = {
    "Premier League": "Live Premier League",
    "Serie A": "Live Serie A",
    "Bundesliga": "Live Bundesliga",
    "La Liga": "Live La Liga",
    "Ligue 1": "Live Ligue 1",
    "UEFA Champions League": "Live UEFA Champions League",
    "UEFA Europa League": "Live UEFA Europa League",
    "UEFA Europa Conference League": "Live UEFA Conference League",
    "Tennis": "Live Tennis"
}

# ================== HELPER ==================
def fetch_text_sync(url: str, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; EuroVN/9.0)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8")
    except:
        return ""

def is_healthy(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "VLC/3.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            return r.getcode() < 400
    except:
        return False

def is_low_resolution(name: str) -> bool:
    n = name.lower()
    return any(x in n for x in ["sd", "360p", "480p", "576p", "low res", "low quality"])

def normalize(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return " ".join(c for c in s if unicodedata.category(c) != "Mn")

def vn_time(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC")).astimezone(TIMEZONE)
    return dt.strftime("%d/%m %I:%M %p")

# ================== SOFASCORE ASYNC ==================
async def get_channel_name(session, channel_id):
    url = f"https://api.sofascore.com/api/v1/tv/channel/{channel_id}/schedule"
    try:
        res = await session.get(url, impersonate="chrome120", timeout=5)
        if res.status_code == 200:
            return res.json().get('channel', {}).get('name', 'Unknown')
    except:
        pass
    return "Unknown"

async def get_tv_data(session, event_id):
    url = f"https://api.sofascore.com/api/v1/tv/event/{event_id}/country-channels"
    try:
        res = await session.get(url, impersonate="chrome120", timeout=10)
        if res.status_code != 200: return []
        data = res.json().get('countryChannels', {})
        broadcasters = []
        for code, cids in data.items():
            country = pycountry.countries.get(alpha_2=code).name if pycountry.countries.get(alpha_2=code) else code
            names = await asyncio.gather(*[get_channel_name(session, cid) for cid in cids])
            clean = list(set([n for n in names if n != "Unknown"]))
            if clean:
                broadcasters.append({"country": country, "channels": clean})
        return broadcasters
    except:
        return []

async def fetch_event(session, event_id, sport, now_ts):
    url = f"https://api.sofascore.com/api/v1/event/{event_id}"
    try:
        res = await session.get(url, impersonate="chrome120", timeout=10)
        if res.status_code != 200: return None
        ev = res.json().get('event', {})
        start_ts = ev.get('startTimestamp')
        if not start_ts or not (now_ts <= start_ts <= now_ts + 86400):
            return None

        tv = await get_tv_data(session, event_id)

        if sport == "tennis":
            league = "Tennis"
            match = f"{ev.get('homeTeam', {}).get('name', '')} vs {ev.get('awayTeam', {}).get('name', '')}"
        else:
            league_raw = ev.get('tournament', {}).get('name', 'Unknown')
            league_lower = league_raw.lower()

            # Lọc giải đấu bằng từ khóa (fix miss "LaLiga" / "La Liga EA Sports")
            if not any(kw in league_lower for kw in ALLOWED_LEAGUE_KEYWORDS):
                return None

            home = ev.get('homeTeam', {}).get('name', '').lower()
            away = ev.get('awayTeam', {}).get('name', '').lower()
            if not (any(t in home for t in ALLOWED_TEAMS) or any(t in away for t in ALLOWED_TEAMS)):
                return None

            # Chuẩn hóa tên giải để group đúng
            if "premier" in league_lower:
                league = "Premier League"
            elif "serie" in league_lower:
                league = "Serie A"
            elif "bundes" in league_lower:
                league = "Bundesliga"
            elif "la liga" in league_lower or "laliga" in league_lower:
                league = "La Liga"
            elif "ligue" in league_lower:
                league = "Ligue 1"
            elif "champions" in league_lower:
                league = "UEFA Champions League"
            elif "europa league" in league_lower:
                league = "UEFA Europa League"
            elif "conference" in league_lower:
                league = "UEFA Europa Conference League"
            else:
                league = league_raw

            match = f"{ev.get('homeTeam', {}).get('name', '')} vs {ev.get('awayTeam', {}).get('name', '')}"

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
    now = datetime.now()
    dates = [now.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")]
    print(f"Fetching {sport} trong 24 giờ tới...")
    all_results = []
    now_ts = int(datetime.now(TIMEZONE).timestamp())

    for date_str in dates:
        url = f"https://www.sofascore.com/api/v1/sport/{sport}/scheduled-events/{date_str}"
        res = await session.get(url, impersonate="chrome120", timeout=30)
        if res.status_code != 200: continue
        events = res.json().get('events', [])
        tasks = [fetch_event(session, e['id'], sport, now_ts) for e in events]
        results = await asyncio.gather(*tasks)
        all_results.extend([r for r in results if r])

    return all_results

# ================== M3U PARSER – GIỮ NGUYÊN TẤT CẢ EXTRA LINES ==================
def parse_m3u(content):
    channels = []
    current = {}
    extra = []
    for line in content.split('\n'):
        line = line.strip()
        if not line: continue
        if line.startswith('#EXTINF'):
            if current.get('name') and current.get('url'):
                if extra: current['extra'] = extra[:]
                channels.append(current)
            current = {}
            extra = []
            params = re.findall(r'([a-zA-Z-]+)="([^"]*)"', line)
            current['params'] = {k.lower(): v for k,v in params}
            name_part = line.split(',', 1)
            current['name'] = unquote(name_part[1].strip()) if len(name_part)>1 else "Unknown"
        elif line.startswith('http'):
            if current:
                current['url'] = line
                if extra: current['extra'] = extra[:]
                channels.append(current)
                current = {}
                extra = []
        elif line.startswith('#'):                     # GIỮ TẤT CẢ DÒNG BẮT ĐẦU BẰNG #
            extra.append(line)                         # #KODIPROP, #EXTHTTP, #EXTVLCOPT, #EXTGRP, #EXT-X-...
    if current.get('name') and current.get('url'):
        if extra: current['extra'] = extra[:]
        channels.append(current)
    return channels

# ================== MAIN ==================
async def main():
    start = time.time()
    vn_now = datetime.now(TIMEZONE)
    print("🔄 Bắt đầu lấy lịch SofaScore TRONG 24 GIỜ TỚI...")

    all_games = []
    async with AsyncSession() as session:
        for sport in ["football", "tennis"]:
            games = await process_24h(session, sport)
            all_games.extend(games)
            await asyncio.sleep(2)

    # schedule.json
    today_str = datetime.now().strftime("%Y%m%d")
    schedule = {
        today_str: {
            "date": datetime.now().strftime("%A, %d/%m"),
            "games": all_games
        }
    }

    day = schedule[today_str]
    seen = {}
    deduped = []
    for g in day["games"]:
        key = normalize(g["match"]) + "|" + g["time"]
        if key not in seen:
            seen[key] = g
            deduped.append(g)
    day["games"] = [g for g in deduped if datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE) > vn_now]

    output = {"updated": vn_now.strftime("%Y-%m-%d %H:%M VN"), "days": schedule}
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"✅ schedule.json: {len(day['games'])} trận trong 24 giờ tới")

    # ================== TẠO live_schedule.m3u ==================
    print("📥 Đang lọc kênh M3U...")
    m3u_links = [line.strip() for line in open(M3U_LIST_FILE, encoding='utf-8') if line.strip().startswith('http')]

    all_ch = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(lambda u: (u, fetch_text_sync(u)), url): url for url in m3u_links}
        for fut in as_completed(futures):
            try:
                _, content = fut.result()
                chs = parse_m3u(content)
                for ch in chs:
                    if is_low_resolution(ch.get('name', '')): continue
                    all_ch.append(ch)
            except:
                continue

    unique_ch = list({ch['url']: ch for ch in all_ch if ch.get('url')}.values())
    valid_ch = [ch for ch in unique_ch if is_healthy(ch['url'])]

    live_events = []
    seen_urls = set()
    for g in day["games"]:
        try:
            if datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE) <= vn_now:
                continue
            for tv in g.get("tv_channels", []):
                for ch_name in tv.get("channels", []):
                    matching = [ch for ch in valid_ch if ch_name.lower() in ch['name'].lower()]
                    for ch in matching:
                        url = ch['url']
                        if url in seen_urls: continue
                        seen_urls.add(url)
                        display_name = f"{g['time']} | {g['match']} ({ch_name})"
                        live_events.append({
                            "datetime": datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE),
                            "name": display_name,
                            "channel": ch,
                            "league": g["league"]
                        })
        except:
            continue

    live_events.sort(key=lambda x: x["datetime"])

    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ev in live_events:
            ch = ev["channel"]
            group_title = LEAGUE_GROUP_NAME.get(ev["league"], "Live Other")
            extinf = f'#EXTINF:-1 tvg-id="{ch["params"].get("tvg-id","")}" group-title="{group_title}"'
            if ch["params"].get("tvg-logo"):
                extinf += f' tvg-logo="{ch["params"]["tvg-logo"]}"'
            extinf += f',{ev["name"]}'
            f.write(extinf + "\n")
            if 'extra' in ch:
                for line in ch['extra']:
                    if not line.startswith('#EXTINF'):
                        f.write(line + "\n")
            f.write(ch['url'] + "\n")

    elapsed = time.time() - start
    print(f"\n🎉 HOÀN THÀNH!")
    print(f"   • schedule.json: {len(day['games'])} trận trong 24 giờ tới")
    print(f"   • live_schedule.m3u: {len(live_events)} kênh (9 nhóm chính xác + tất cả extra lines)")
    print(f"   • Thời gian: {elapsed:.1f}s")

if __name__ == "__main__":
    asyncio.run(main())
