"""
euro_vn_full_schedule_live.py
================================
BẢN HOÀN CHỈNH – 48 GIỜ TỚI + LỌC THEO GIẢI + ĐỘI RIÊNG + TÍCH HỢP WHERE'S THE MATCH
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
from difflib import SequenceMatcher

import pycountry
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup

# ================== CẤU HÌNH ==================
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
M3U_LIST_FILE = "M3U_list.txt"
SCHEDULE_FILE = "schedule.json"
LIVE_M3U = "live_schedule.m3u"

# DANH SÁCH ĐỘI RIÊNG TỪNG GIẢI (theo yêu cầu mới nhất của bạn)
ALLOWED_TEAMS_PER_LEAGUE = {
    "Premier League": {"arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
                       "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
                       "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
                       "west ham united", "wolverhampton"},
    "Serie A": {"inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"},
    "La Liga": {"barcelona", "real madrid", "atlético"},
    "Bundesliga": {"bayern", "borussia dortmund", "bayer leverkusen"},
    "Ligue 1": {"psg", "olympique marseille"},
    # UEFA leagues: không giới hạn đội
    "UEFA Champions League": None,
    "UEFA Europa League": None,
    "UEFA Europa Conference League": None,
}

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

def similar(a: str, b: str) -> float:
    """Tính độ tương đồng giữa hai chuỗi (dùng để so khớp tên đội)"""
    return SequenceMatcher(None, a, b).ratio()

# ================== SOFASCORE (48 GIỜ TỚI + LỌC NGHIÊM) ==================
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

async def fetch_event(session, event_id, sport, now_ts, max_ts):
    url = f"https://api.sofascore.com/api/v1/event/{event_id}"
    try:
        res = await session.get(url, impersonate="chrome120", timeout=10)
        if res.status_code != 200: return None
        ev = res.json().get('event', {})
        start_ts = ev.get('startTimestamp')
        if not start_ts or not (now_ts <= start_ts <= max_ts):
            return None

        tv = await get_tv_data(session, event_id)

        if sport == "tennis":
            league = "Tennis"
            match = f"{ev.get('homeTeam', {}).get('name', '')} vs {ev.get('awayTeam', {}).get('name', '')}"
        else:
            league_raw = ev.get('tournament', {}).get('name', 'Unknown')
            league_lower = league_raw.lower()

            # Lọc giải đấu (fix LaLiga EA Sports, La Liga, Laliga...)
            if not any(kw in league_lower for kw in ["premier league", "serie a", "bundesliga", "la liga", "laliga", "ligue 1", "uefa champions", "uefa europa league", "conference league"]):
                return None

            # Xác định tên giải chuẩn
            if "la liga" in league_lower or "laliga" in league_lower:
                league = "La Liga"
            elif "premier" in league_lower:
                league = "Premier League"
            elif "serie" in league_lower:
                league = "Serie A"
            elif "bundes" in league_lower:
                league = "Bundesliga"
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

            # Lọc đội theo giải
            allowed_teams = ALLOWED_TEAMS_PER_LEAGUE.get(league)
            if allowed_teams is not None:  # chỉ kiểm tra nếu có danh sách
                home = ev.get('homeTeam', {}).get('name', '').lower()
                away = ev.get('awayTeam', {}).get('name', '').lower()
                if not (any(t in home for t in allowed_teams) or any(t in away for t in allowed_teams)):
                    return None

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

async def process_48h(session, sport):
    now = datetime.now()
    dates = [now.strftime("%Y-%m-%d"), 
             (now + timedelta(days=1)).strftime("%Y-%m-%d"),
             (now + timedelta(days=2)).strftime("%Y-%m-%d")]
    print(f"Fetching {sport} trong 48 giờ tới...")
    all_results = []
    now_ts = int(datetime.now(TIMEZONE).timestamp())
    max_ts = now_ts + 172800  # 48 giờ

    for date_str in dates:
        url = f"https://www.sofascore.com/api/v1/sport/{sport}/scheduled-events/{date_str}"
        res = await session.get(url, impersonate="chrome120", timeout=30)
        if res.status_code != 200: continue
        events = res.json().get('events', [])
        tasks = [fetch_event(session, e['id'], sport, now_ts, max_ts) for e in events]
        results = await asyncio.gather(*tasks)
        all_results.extend([r for r in results if r])

    return all_results

# ================== WHERE'S THE MATCH SCRAPER ==================
UK_CHANNELS = [
    "Sky Sports Main Event", "Sky Sports Premier League", "Sky Sports Football",
    "Sky Sports Arena", "Sky Sports Action", "Sky Sports Mix", "Sky Sports News",
    "Sky Sports+", "Sky Sports", "TNT Sports 1", "TNT Sports 2", "TNT Sports 3",
    "TNT Sports 4", "TNT Sports Ultimate", "TNT Sports Extra", "TNT Sports",
    "BBC One", "BBC Two", "BBC iPlayer", "ITV1", "ITV4", "ITVX", "Channel 4",
    "Amazon Prime Video", "Amazon Prime", "Premier Sports 1", "Premier Sports 2",
    "Premier Sports", "BT Sport 1", "BT Sport 2", "BT Sport 3", "LaLigaTV",
    "FreeSports", "discovery+", "Discovery+", "DAZN"
]

async def fetch_wtm_fixtures() -> list:
    """
    Lấy danh sách trận đấu từ Where's The Match (https://www.wheresthematch.com/live-football-on-tv/)
    Trả về list các dict chứa: home, away, kickoff_utc (timestamp), competition, channels
    """
    url = "https://www.wheresthematch.com/live-football-on-tv/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        async with AsyncSession() as session:
            resp = await session.get(url, impersonate="chrome120", headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"[WTM] HTTP {resp.status_code}")
                return []
            html = resp.text
    except Exception as e:
        print(f"[WTM] Request failed: {e}")
        return []

    # Parse HTML trong thread riêng để không block event loop
    loop = asyncio.get_event_loop()
    fixtures = await loop.run_in_executor(None, _parse_wtm_html, html)
    return fixtures

def _parse_wtm_html(html: str) -> list:
    soup = BeautifulSoup(html, 'lxml')
    rows = soup.select('tr[itemscope][itemtype*="BroadcastEvent"]')
    fixtures = []

    for row in rows:
        # Bỏ qua các trận nữ
        if re.search(r"women'?s|womens|ladies", row.get_text(), re.I):
            continue

        # ---- Đội nhà / đội khách ----
        team_links = row.select('td.fixture-details a[title]')
        home = away = None
        if len(team_links) >= 2:
            home = team_links[0].get('title') or team_links[0].text.strip()
            away = team_links[-1].get('title') or team_links[-1].text.strip()
        else:
            # fallback: parse text "Team A v Team B"
            fixture_cell = row.select_one('td.fixture-details')
            if fixture_cell:
                text = fixture_cell.get_text(strip=True)
                m = re.search(r'(.+?)\s+(?:v|vs|versus|–|-)\s+(.+)', text, re.I)
                if m:
                    home, away = m.groups()
        if not home or not away:
            continue
        home = home.strip()
        away = away.strip()

        # ---- Thời gian (UTC) ----
        kickoff_utc = None
        meta = row.select_one('td.start-details meta[itemprop="startDate"]')
        if meta and meta.get('content'):
            iso = meta['content']
            try:
                # Xử lý định dạng ISO (có thể có Z)
                if iso.endswith('Z'):
                    iso = iso.replace('Z', '+00:00')
                dt = datetime.fromisoformat(iso)
                kickoff_utc = int(dt.timestamp())
            except:
                pass
        if not kickoff_utc:
            # Nếu không có ISO, bỏ qua (không xác định được giờ chính xác)
            continue

        # ---- Giải đấu ----
        comp_elem = row.select_one('td.competition-name span')
        if comp_elem:
            competition = comp_elem.text.strip()
        else:
            comp_elem = row.select_one('td.competition-name')
            competition = comp_elem.text.strip() if comp_elem else ""

        # ---- Kênh phát sóng ----
        channels = set()
        # Từ các ảnh logo
        imgs = row.select('td.channel-details img')
        for img in imgs:
            alt = img.get('alt', '').strip()
            title = img.get('title', '').strip()
            name = alt or title
            if name:
                # Bỏ hậu tố "logo"
                name = re.sub(r'\s+logo$', '', name, flags=re.I).strip()
                channels.add(name)
        # Từ text trong ô (có thể có tên kênh dạng chữ)
        chan_cell = row.select_one('td.channel-details')
        if chan_cell:
            text = chan_cell.get_text(separator=' ', strip=True)
            if text:
                # Tách bằng dấu phẩy hoặc xuống dòng
                for part in re.split(r'[,;]', text):
                    part = part.strip()
                    if part and not any(x in part.lower() for x in ['logo', 'image']):
                        channels.add(part)

        fixtures.append({
            'home': home,
            'away': away,
            'kickoff_utc': kickoff_utc,
            'competition': competition,
            'channels': list(channels)
        })

    return fixtures

# ================== M3U PARSER – GIỮ NGUYÊN TẤT CẢ EXTRA ==================
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
        elif line.startswith('#'):   # GIỮ TẤT CẢ: #KODIPROP, #EXTHTTP, #EXTVLCOPT...
            extra.append(line)
    if current.get('name') and current.get('url'):
        if extra: current['extra'] = extra[:]
        channels.append(current)
    return channels

# ================== MAIN ==================
async def main():
    start = time.time()
    vn_now = datetime.now(TIMEZONE)
    print("🔄 Bắt đầu lấy lịch SofaScore 48 GIỜ TỚI (lọc nghiêm theo giải + đội)...")

    all_games = []
    async with AsyncSession() as session:
        for sport in ["football", "tennis"]:
            games = await process_48h(session, sport)
            all_games.extend(games)
            await asyncio.sleep(2)

    # --- BỔ SUNG: Lấy dữ liệu từ Where's The Match và merge ---
    print("📡 Đang lấy dữ liệu từ Where's The Match...")
    wtm_fixtures = await fetch_wtm_fixtures()
    now_ts = int(datetime.now(TIMEZONE).timestamp())
    # Lọc các trận trong 48h tới
    wtm_filtered = [f for f in wtm_fixtures if now_ts <= f['kickoff_utc'] <= now_ts + 172800]
    print(f"   • WTM: {len(wtm_filtered)} trận trong 48h tới")

    if wtm_filtered:
        # Merge vào all_games (chỉ các trận football)
        for game in all_games:
            # Bỏ qua tennis
            if game.get('league') == 'Tennis':
                continue
            # Tách tên đội từ match (định dạng "Home vs Away")
            match_parts = game['match'].split(' vs ')
            if len(match_parts) != 2:
                continue
            sof_home = normalize(match_parts[0])
            sof_away = normalize(match_parts[1])

            best_match = None
            best_score = 0.0
            for wtm in wtm_filtered:
                wtm_home = normalize(wtm['home'])
                wtm_away = normalize(wtm['away'])
                score_home = similar(sof_home, wtm_home)
                score_away = similar(sof_away, wtm_away)
                avg_score = (score_home + score_away) / 2
                time_diff = abs(game['kick_utc'] - wtm['kickoff_utc'])
                # Ngưỡng: độ tương đồng > 0.7 và chênh lệch thời gian < 1 giờ
                if avg_score > best_score and time_diff < 3600:
                    best_score = avg_score
                    best_match = wtm
            if best_match and best_score > 0.7:
                uk_channels = best_match['channels']
                if uk_channels:
                    # Thêm kênh UK vào tv_channels
                    found = False
                    for tv in game['tv_channels']:
                        if tv['country'] == 'United Kingdom':
                            tv['channels'] = list(set(tv['channels'] + uk_channels))
                            found = True
                            break
                    if not found:
                        game['tv_channels'].append({
                            'country': 'United Kingdom',
                            'channels': uk_channels
                        })
        print("   • Đã merge kênh UK vào các trận tương ứng")
    # --- KẾT THÚC BỔ SUNG ---

    # schedule.json
    today_str = datetime.now().strftime("%Y%m%d")
    schedule = {today_str: {"date": datetime.now().strftime("%A, %d/%m"), "games": all_games}}

    day = schedule[today_str]
    seen = {}
    deduped = []
    for g in day["games"]:
        key = normalize(g["match"]) + "|" + g["time"]
        if key not in seen:
            seen[key] = g
            deduped.append(g)
    # Lọc các trận đã qua (so với giờ hiện tại VN)
    day["games"] = [g for g in deduped if datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE) > vn_now]

    output = {"updated": vn_now.strftime("%Y-%m-%d %H:%M VN"), "days": schedule}
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"✅ schedule.json: {len(day['games'])} trận")

    # ================== M3U ==================
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
            if datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE) <= vn_now: continue
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
    print(f"   • schedule.json: {len(day['games'])} trận")
    print(f"   • live_schedule.m3u: {len(live_events)} kênh (9 nhóm chính xác)")

if __name__ == "__main__":
    asyncio.run(main())
