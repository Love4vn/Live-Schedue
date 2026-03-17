"""
euro_vn_full_schedule_live.py
================================
BẢN HOÀN CHỈNH – 24 GIỜ TỚI + LỌC THEO GIẢI + ĐỘI RIÊNG
TÍCH HỢP: SofaScore (chính) + LiveSportsOnTV (bổ sung kênh UK)
Tối ưu ghép kênh M3U với matching thông minh
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
from typing import List, Dict, Any, Optional

import pycountry
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ================== CẤU HÌNH ==================
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
UK_TIMEZONE = ZoneInfo("Europe/London")
M3U_LIST_FILE = "M3U_list.txt"
SCHEDULE_FILE = "schedule.json"
LIVE_M3U = "live_schedule.m3u"

# Danh sách giải tennis được phép (ATP và Grand Slam)
ALLOWED_TENNIS_TOURNAMENTS = {
    "atp", "atp tour", "atp world tour", "grand slam", "australian open",
    "roland garros", "french open", "wimbledon", "us open", "nitto atp finals",
    "atp masters", "atp 1000", "atp 500", "atp 250"
}

# Danh sách đội riêng từng giải
ALLOWED_TEAMS_PER_LEAGUE = {
    "Premier League": {"arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
                       "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
                       "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
                       "west ham united", "wolverhampton"},
    "Serie A": {"inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"},
    "La Liga": {"barcelona", "real madrid", "atlético"},
    "Bundesliga": {"bayern", "borussia dortmund", "bayer leverkusen"},
    "Ligue 1": {"psg", "olympique marseille"},
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
    return SequenceMatcher(None, a, b).ratio()

def normalize_channel_name(name: str) -> str:
    """Chuẩn hóa tên kênh để so sánh: loại bỏ các từ phổ biến, dấu, lowercase"""
    name = name.lower()
    # Loại bỏ các từ thừa thường gặp
    name = re.sub(r'\b(hd|uhd|4k|fhd|vip|plus|extra|usa|uk|us|tv|channel|network|sports?|premium|maximo?)\b', '', name)
    # Loại bỏ dấu ngoặc và nội dung trong ngoặc
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'\[[^\]]*\]', '', name)
    # Loại bỏ ký tự đặc biệt, giữ lại chữ và số
    name = re.sub(r'[^\w\s]', ' ', name)
    # Chuẩn hóa khoảng trắng
    name = ' '.join(name.split())
    # Bỏ dấu tiếng Việt nếu có
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ascii')
    return name

def is_channel_match(ch_name: str, m3u_name: str) -> bool:
    """Kiểm tra xem tên kênh từ lịch có khớp với tên kênh trong M3U không"""
    if not ch_name or not m3u_name:
        return False
    ch_norm = normalize_channel_name(ch_name)
    m3u_norm = normalize_channel_name(m3u_name)
    # Nếu tên gốc ngắn (<=5 ký tự) thì so sánh chính xác
    if len(ch_norm) <= 5:
        return ch_norm == m3u_norm
    # Nếu dài hơn, dùng SequenceMatcher với ngưỡng 0.9
    # Nhưng cũng kiểm tra độ dài không chênh lệch quá 3
    if abs(len(ch_norm) - len(m3u_norm)) > 3:
        return False
    return similar(ch_norm, m3u_norm) >= 0.9

# ================== SOFASCORE ==================
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

async def fetch_sofascore_event(session, event_id, sport, now_ts, max_ts):
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
            tournament = ev.get('tournament', {}).get('name', '').lower()
            # Lọc chỉ các giải ATP và Grand Slam
            if not any(keyword in tournament for keyword in ALLOWED_TENNIS_TOURNAMENTS):
                return None
            league = "Tennis"
            match = f"{ev.get('homeTeam', {}).get('name', '')} vs {ev.get('awayTeam', {}).get('name', '')}"
            return {
                "league": league,
                "time": vn_time(start_ts),
                "match": match,
                "kick_utc": start_ts,
                "tv_channels": tv,
                "tournament": ev.get('tournament', {}).get('name')
            }
        else:
            league_raw = ev.get('tournament', {}).get('name', 'Unknown')
            league_lower = league_raw.lower()

            if not any(kw in league_lower for kw in ["premier league", "serie a", "bundesliga", "la liga", "laliga", "ligue 1", "uefa champions", "uefa europa league", "conference league"]):
                return None

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

            allowed_teams = ALLOWED_TEAMS_PER_LEAGUE.get(league)
            if allowed_teams is not None:
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
                "tv_channels": tv,
                "tournament": league_raw
            }
    except:
        return None

async def scrape_sofascore() -> List[Dict]:
    """Lấy dữ liệu từ SofaScore trong 24 giờ tới"""
    all_games = []
    async with AsyncSession() as session:
        for sport in ["football", "tennis"]:
            now = datetime.now()
            dates = [now.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")]
            now_ts = int(datetime.now(TIMEZONE).timestamp())
            max_ts = now_ts + 86400  # 24 giờ

            for date_str in dates:
                url = f"https://www.sofascore.com/api/v1/sport/{sport}/scheduled-events/{date_str}"
                res = await session.get(url, impersonate="chrome120", timeout=30)
                if res.status_code != 200: continue
                events = res.json().get('events', [])
                tasks = [fetch_sofascore_event(session, e['id'], sport, now_ts, max_ts) for e in events]
                results = await asyncio.gather(*tasks)
                all_games.extend([r for r in results if r])
            await asyncio.sleep(2)
    return all_games

# ================== LIVESPORTSONTV ==================
# Cấu hình các giải cho LiveSportsOnTV (đồng nhất với SofaScore)
LIVESPORTS_LEAGUES = {
    "Premier League": {
        "url": "https://www.livesportsontv.com/league/premier-league",
        "teams": ALLOWED_TEAMS_PER_LEAGUE["Premier League"]
    },
    "Serie A": {
        "url": "https://www.livesportsontv.com/league/serie-a",
        "teams": ALLOWED_TEAMS_PER_LEAGUE["Serie A"]
    },
    "La Liga": {
        "url": "https://www.livesportsontv.com/league/la-liga",
        "teams": ALLOWED_TEAMS_PER_LEAGUE["La Liga"]
    },
    "Bundesliga": {
        "url": "https://www.livesportsontv.com/league/bundesliga-5",
        "teams": ALLOWED_TEAMS_PER_LEAGUE["Bundesliga"]
    },
    "Ligue 1": {
        "url": "https://www.livesportsontv.com/league/ligue-1-3",
        "teams": ALLOWED_TEAMS_PER_LEAGUE["Ligue 1"]
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
    "Tennis": {
        "url": "https://www.livesportsontv.com/league/atp",  # ATP là chính, nhưng cần lọc Grand Slam? Trang này có cả WTA?
        "teams": None
    }
    # Có thể thêm WTA nếu cần, nhưng ta chỉ lấy ATP và Grand Slam từ SofaScore
}

async def scrape_livesportsontv() -> List[Dict]:
    """Lấy dữ liệu từ LiveSportsOnTV trong 24 giờ tới"""
    all_games = []
    now_ts = int(datetime.now(TIMEZONE).timestamp())
    max_ts = now_ts + 86400
    today = datetime.now()
    target_day = str(today.day)
    target_month = today.strftime("%b").lower()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        page = await browser.new_page()
        # Thiết lập timeout
        page.set_default_navigation_timeout(120000)
        page.set_default_timeout(60000)

        for league_name, config in LIVESPORTS_LEAGUES.items():
            url = config["url"]
            team_filter = config.get("teams")
            print(f"   [LiveSports] Đang xử lý {league_name}...")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=120000)
            except Exception as e:
                print(f"   [LiveSports] Lỗi khi tải {league_name}: {e}")
                continue

            # Scroll để load hết
            for _ in range(4):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1.5)

            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            game_rows = soup.find_all('div', class_='event--wrapp')

            for row in game_rows:
                try:
                    # Lọc ngày
                    date_div = row.find('div', class_='event__info--date')
                    if not date_div:
                        continue
                    game_day = date_div.find('b').get_text(strip=True) if date_div.find('b') else ""
                    game_month = date_div.find('span').get_text(strip=True).lower() if date_div.find('span') else ""
                    if game_day != target_day or game_month != target_month:
                        continue

                    # Lấy thời gian và chuyển thành timestamp
                    time_tag = row.find('time')
                    if not time_tag:
                        continue
                    dt_attr = time_tag.get('datetime')
                    if dt_attr:
                        dt_obj = datetime.fromisoformat(dt_attr.replace('Z', '+00:00'))
                        if dt_obj.tzinfo is None:
                            dt_obj = dt_obj.replace(tzinfo=UK_TIMEZONE)
                        kick_utc = int(dt_obj.timestamp())
                    else:
                        time_str = time_tag.get_text(strip=True)
                        # Kết hợp ngày tháng năm (năm hiện tại)
                        year = today.year
                        dt_str = f"{game_day} {game_month.capitalize()} {year} {time_str}"
                        try:
                            dt_obj = datetime.strptime(dt_str, "%d %b %Y %H:%M")
                        except:
                            continue
                        dt_obj = dt_obj.replace(tzinfo=UK_TIMEZONE)
                        # Nếu thời gian đã qua so với hiện tại ở UK, có thể là năm sau (trường hợp cuối năm)
                        now_uk = datetime.now(UK_TIMEZONE)
                        if dt_obj < now_uk and (now_uk.month == 12 and dt_obj.month == 1):
                            dt_obj = dt_obj.replace(year=year+1)
                        kick_utc = int(dt_obj.timestamp())

                    if not (now_ts <= kick_utc <= max_ts):
                        continue

                    # Lấy đội
                    home_elem = row.find('div', class_=lambda c: c and 'event__participant--home' in c)
                    away_elem = row.find('div', class_=lambda c: c and 'event__participant--away' in c)
                    if not home_elem or not away_elem:
                        continue
                    home_team = home_elem.get_text(strip=True)
                    away_team = away_elem.get_text(strip=True)
                    match = f"{home_team} vs {away_team}"

                    # Lọc đội nếu có
                    if team_filter is not None:
                        if not any(t.lower() in home_team.lower() or t.lower() in away_team.lower() for t in team_filter):
                            continue

                    # Lấy kênh
                    channels = []
                    channel_list = row.find('ul', class_='event__tags')
                    if channel_list:
                        for link in channel_list.find_all('a'):
                            aria = link.get('aria-label')
                            if aria:
                                channels.append(aria.strip())

                    all_games.append({
                        "league": league_name,
                        "time": vn_time(kick_utc),
                        "match": match,
                        "kick_utc": kick_utc,
                        "tv_channels": [{"country": "United Kingdom", "channels": channels}] if channels else [],
                        "source": "livesportsontv"
                    })
                except Exception as e:
                    continue

        await browser.close()
    return all_games

# ================== MERGE ==================
def merge_games(sofascore_games: List[Dict], livesports_games: List[Dict]) -> List[Dict]:
    """Merge dữ liệu từ LiveSports vào SofaScore (bổ sung kênh UK)"""
    # Tạo dict index cho SofaScore để dễ tìm
    # Đối với football: index theo (league, kick_utc) + tên đội
    # Đối với tennis: index theo kick_utc (vì tên người khác nhau)
    sofascore_by_time = {}
    for game in sofascore_games:
        if game['league'] == 'Tennis':
            sofascore_by_time[game['kick_utc']] = game
        else:
            # Không index, sẽ dùng vòng lặp
            pass

    # Merge từng trận LiveSports
    for ls in livesports_games:
        if ls['league'] == 'Tennis':
            # Tennis: tìm theo thời gian (sai số 1 giờ)
            for game in sofascore_games:
                if game['league'] == 'Tennis' and abs(game['kick_utc'] - ls['kick_utc']) < 3600:
                    if ls['tv_channels'] and ls['tv_channels'][0]['channels']:
                        found = False
                        for tv in game['tv_channels']:
                            if tv['country'] == 'United Kingdom':
                                tv['channels'] = list(set(tv['channels'] + ls['tv_channels'][0]['channels']))
                                found = True
                                break
                        if not found:
                            game['tv_channels'].append({
                                'country': 'United Kingdom',
                                'channels': ls['tv_channels'][0]['channels']
                            })
                    break
        else:
            # Football: tìm theo tên đội và thời gian
            parts = ls['match'].split(' vs ')
            if len(parts) != 2:
                continue
            ls_home = normalize(parts[0])
            ls_away = normalize(parts[1])
            best_match = None
            best_score = 0.0
            for game in sofascore_games:
                if game['league'] == 'Tennis':
                    continue
                sof_parts = game['match'].split(' vs ')
                if len(sof_parts) != 2:
                    continue
                sof_home = normalize(sof_parts[0])
                sof_away = normalize(sof_parts[1])
                score_home = similar(sof_home, ls_home)
                score_away = similar(sof_away, ls_away)
                avg_score = (score_home + score_away) / 2
                time_diff = abs(game['kick_utc'] - ls['kick_utc'])
                if avg_score > best_score and time_diff < 3600:
                    best_score = avg_score
                    best_match = game
            if best_match and best_score > 0.7:
                uk_channels = ls['tv_channels'][0]['channels'] if ls['tv_channels'] else []
                if uk_channels:
                    found = False
                    for tv in best_match['tv_channels']:
                        if tv['country'] == 'United Kingdom':
                            tv['channels'] = list(set(tv['channels'] + uk_channels))
                            found = True
                            break
                    if not found:
                        best_match['tv_channels'].append({
                            'country': 'United Kingdom',
                            'channels': uk_channels
                        })
    return sofascore_games

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
        elif line.startswith('#'):
            extra.append(line)
    if current.get('name') and current.get('url'):
        if extra: current['extra'] = extra[:]
        channels.append(current)
    return channels

# ================== MAIN ==================
async def main():
    start = time.time()
    vn_now = datetime.now(TIMEZONE)
    print("🔄 Bắt đầu lấy lịch 24 GIỜ TỚI từ SofaScore và LiveSportsOnTV...")

    # 1. SofaScore
    print("📡 Đang lấy dữ liệu từ SofaScore...")
    sofascore_games = await scrape_sofascore()
    print(f"   ✅ SofaScore: {len(sofascore_games)} trận")

    # 2. LiveSportsOnTV
    print("📡 Đang lấy dữ liệu từ LiveSportsOnTV...")
    livesports_games = await scrape_livesportsontv()
    print(f"   ✅ LiveSportsOnTV: {len(livesports_games)} trận")

    # 3. Merge
    print("🔄 Đang merge dữ liệu...")
    merged_games = merge_games(sofascore_games, livesports_games)

    # 4. schedule.json (chỉ lấy các trận chưa qua)
    today_str = datetime.now().strftime("%Y%m%d")
    schedule = {today_str: {"date": datetime.now().strftime("%A, %d/%m"), "games": merged_games}}
    day = schedule[today_str]

    # Lọc trùng và trận đã qua
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
    print(f"✅ schedule.json: {len(day['games'])} trận")

    # ================== M3U ==================
    print("📥 Đang lọc kênh M3U (matching thông minh)...")
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
                    matching = [ch for ch in valid_ch if is_channel_match(ch_name, ch['name'])]
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
    print(f"   • live_schedule.m3u: {len(live_events)} kênh (matching thông minh)")

if __name__ == "__main__":
    asyncio.run(main())
