"""
euro_vn_full_schedule_live.py
================================
BẢN HOÀN CHỈNH CUỐI CÙNG – CHỈ HÔM NAY (football + tennis)
- Bóng đá: CHỈ trận có đội trong list bạn đưa + chỉ các giải Premier, Serie A, Bundesliga, La Liga, Ligue 1, UCL, UEL, Conference
- Tennis: lấy tất cả
- Group-title chính xác: "Live Premier League", "Live Serie A", ...
- Tên trận: "DD/MM HH:MM | Arsenal vs Man City (Sky Sports Premier League)" (không lặp giải đấu)
- Dedup URL triệt để: cùng link chỉ xuất 1 lần, giữ nguyên #EXTINF + #EXTVLCOPT + #EXTGRP
- Loại SD/low-res + kênh lỗi
- Sắp xếp theo giờ Việt Nam
"""

import asyncio
import json
import re
import unicodedata
import urllib.request
import time
from datetime import datetime
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

# Danh sách đội bóng đá bạn yêu cầu
ALLOWED_TEAMS = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton", "bayern", "borussia dortmund", "bayer leverkusen",
    "inter milan", "ac milan", "napoli", "barcelona", "real madrid", "atlético", "psg",
    "olympique marseille"
}

# Chỉ các giải bạn muốn
ALLOWED_LEAGUES = {
    "Premier League", "Serie A", "Bundesliga", "La Liga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League"
}

# Group-title chính xác theo yêu cầu
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
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; EuroVN/7.0)"})
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

async def fetch_event(session, event_id, sport):
    url = f"https://api.sofascore.com/api/v1/event/{event_id}"
    try:
        res = await session.get(url, impersonate="chrome120", timeout=10)
        if res.status_code != 200: return None
        ev = res.json().get('event', {})
        tv = await get_tv_data(session, event_id)

        if sport == "tennis":
            league = "Tennis"
            match = f"{ev.get('homeTeam', {}).get('name', '')} vs {ev.get('awayTeam', {}).get('name', '')}"
        else:
            league = ev.get('tournament', {}).get('name', 'Unknown')
            match = f"{ev.get('homeTeam', {}).get('name', '')} vs {ev.get('awayTeam', {}).get('name', '')}"

            # LỌC NGHIÊM NGẶT: chỉ giải bạn muốn + đội bạn liệt kê
            if league not in ALLOWED_LEAGUES:
                return None
            home = ev.get('homeTeam', {}).get('name', '').lower()
            away = ev.get('awayTeam', {}).get('name', '').lower()
            if not (any(t in home for t in ALLOWED_TEAMS) or any(t in away for t in ALLOWED_TEAMS)):
                return None

        return {
            "league": league,
            "time": vn_time(ev['startTimestamp']),
            "match": match,
            "kick_utc": ev['startTimestamp'],
            "tv_channels": tv
        }
    except:
        return None

async def process_today(session, sport):
    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")
    url = f"https://www.sofascore.com/api/v1/sport/{sport}/scheduled-events/{date_str}"
    print(f"Fetching {sport} hôm nay...")
    res = await session.get(url, impersonate="chrome120", timeout=30)
    if res.status_code != 200: return []

    events = res.json().get('events', [])
    tasks = [fetch_event(session, e['id'], sport) for e in events]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r]

# ================== M3U PARSER ==================
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
        elif line.startswith('#EXTVLCOPT') or line.startswith('#EXTGRP'):
            extra.append(line)
    if current.get('name') and current.get('url'):
        if extra: current['extra'] = extra[:]
        channels.append(current)
    return channels

# ================== MAIN ==================
async def main():
    start = time.time()
    vn_now = datetime.now(TIMEZONE)
    print("🔄 Bắt đầu lấy lịch SofaScore CHỈ HÔM NAY (chỉ đội bạn liệt kê)...")

    all_games = []
    async with AsyncSession() as session:
        for sport in ["football", "tennis"]:
            games = await process_today(session, sport)
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

    # Dedup + prune
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
    print(f"✅ schedule.json: {len(day['games'])} trận hôm nay")

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

    # Thu thập + dedup URL
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
                        if url in seen_urls:
                            continue
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

    # Xuất M3U với group-title chính xác
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
    print(f"   • schedule.json: {len(day['games'])} trận")
    print(f"   • live_schedule.m3u: {len(live_events)} kênh (9 nhóm chính xác)")
    print(f"   • Thời gian: {elapsed:.1f}s")

if __name__ == "__main__":
    asyncio.run(main())
