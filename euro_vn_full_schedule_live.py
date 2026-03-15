"""
euro_vn_full_schedule_live.py
================================
BẢN HOÀN CHỈNH CUỐI CÙNG – CHỈ LẤY HÔM NAY (football + tennis)
- Bóng đá: CHỈ các trận có đội trong danh sách bạn đưa (Premier League, Serie A, Bundesliga, La Liga, Ligue 1 + UCL/UEL nếu đội nằm trong list)
- Tennis: lấy tất cả
- Kênh: lấy chính xác từ SofaScore TV (Sky Sports Main Event, TNT Sports 1, beIN 1...)
- Loại triệt để: SD/low-res + kênh lỗi
- 1 trận nhiều kênh → giữ hết
- Dedup URL: cùng link chỉ xuất 1 lần (giữ đầy đủ #EXTINF + EXTVLCOPT + EXTGRP của kênh gốc)
- live_schedule.m3u: 9 nhóm riêng + sắp xếp theo giờ VN (AM/PM)
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

# Danh sách đội bóng đá bạn yêu cầu (chỉ lấy trận có ít nhất 1 đội trong list)
ALLOWED_TEAMS = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton", "bayern", "borussia dortmund", "bayer leverkusen",
    "inter milan", "ac milan", "napoli", "barcelona", "real madrid", "atlético", "psg",
    "olympique marseille"
}

LEAGUE_VN_NAME = {
    "Premier League": "Giải Ngoại Hạng Anh",
    "Serie A": "Giải Ý",
    "Bundesliga": "Giải Đức",
    "La Liga": "Giải Tây Ban Nha",
    "Ligue 1": "Giải Pháp",
    "UEFA Champions League": "UEFA Champions League",
    "UEFA Europa League": "UEFA Europa League",
    "UEFA Europa Conference League": "UEFA Conference League",
    "Tennis": "Tennis"
}

# Từ khóa broadcaster để hỗ trợ fallback matching
BROADCAST_KEYWORDS = {
    "sky": ["sky sport", "skysports"],
    "tnt": ["tnt sport", "tntsports"],
    "bein": ["bein sport", "beinsports"],
    "arena": ["arena sport"],
    "astro": ["astro", "supersport"],
    "now": ["now sport", "now tv"],
    "dazn": ["dazn"],
}

# ================== HELPER ==================
def fetch_text_sync(url: str, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; EuroVN/6.0)"})
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
    return any(x in n for x in ["sd", "360p", "480p", "576p", "low res", "low quality", "sd "])

def normalize(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return " ".join(c for c in s if unicodedata.category(c) != "Mn")

def vn_time(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC")).astimezone(TIMEZONE)
    return dt.strftime("%-I:%M %p")

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

            # LỌC ĐỘI BÓNG ĐÁ (chỉ giữ trận có ít nhất 1 đội trong list)
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

# ================== M3U PARSER (đầy đủ) ==================
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
    print("🔄 Bắt đầu lấy lịch SofaScore CHỈ HÔM NAY (chỉ đội bạn liệt kê + Tennis)...")

    all_games = []
    async with AsyncSession() as session:
        for sport in ["football", "tennis"]:
            games = await process_today(session, sport)
            all_games.extend(games)
            await asyncio.sleep(2)

    # schedule.json (chỉ hôm nay)
    today_str = datetime.now().strftime("%Y%m%d")
    schedule = {
        today_str: {
            "date": datetime.now().strftime("%A, %d/%m"),
            "games": all_games
        }
    }

    # Dedup + prune trận cũ
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

    # Thu thập trận + kênh (dedup URL)
    live_events = []
    seen_urls = set()
    for g in day["games"]:
        try:
            if datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE) <= vn_now:
                continue
            for tv in g.get("tv_channels", []):
                for ch_name in tv.get("channels", []):
                    # Tìm kênh M3U khớp tên SofaScore
                    matching = [ch for ch in valid_ch if ch_name.lower() in ch['name'].lower()]
                    for ch in matching:
                        url = ch['url']
                        if url in seen_urls:
                            continue  # dedup URL - giữ nguyên đầy đủ extra lines của kênh gốc
                        seen_urls.add(url)
                        display_name = f"{g['time']} | {g['league']} - {g['match']} ({ch_name})"
                        live_events.append({
                            "datetime": datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE),
                            "name": display_name,
                            "channel": ch,
                            "league": g["league"]
                        })
        except:
            continue

    live_events.sort(key=lambda x: x["datetime"])

    # Xuất M3U
    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ev in live_events:
            ch = ev["channel"]
            group_vn = LEAGUE_VN_NAME.get(ev["league"], "Lịch trực tiếp")
            extinf = f'#EXTINF:-1 tvg-id="{ch["params"].get("tvg-id","")}" group-title="{group_vn}"'
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
    print(f"   • live_schedule.m3u: {len(live_events)} kênh (9 nhóm + sắp xếp giờ VN)")
    print(f"   • Thời gian: {elapsed:.1f}s")

if __name__ == "__main__":
    asyncio.run(main())
