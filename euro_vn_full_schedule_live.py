"""
euro_vn_full_schedule_live.py
================================
BẢN CẬP NHẬT THE SPORTS DB - LẤY CHÍNH XÁC KÊNH PHÁT SÓNG
- Nguồn dữ liệu: TheSportsDB API (Free Tier)
- Chỉ lấy các kênh cụ thể đang chiếu trận đó (VD: Viaplay Sports 2, DAZN LaLiga)
- Tự động đối chiếu chính xác từ khóa vào file M3U.
- Output: schedule.json + live_schedule.m3u (chỉ gồm kênh Live & Khớp trận)
"""

import json
import re
import unicodedata
import urllib.request
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote

# ================== CẤU HÌNH ==================
DAYS_AHEAD = 5
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
M3U_LIST_FILE = "M3U_list.txt"
SCHEDULE_FILE = "schedule.json"
LIVE_M3U = "live_schedule.m3u"
TSDB_API_KEY = "3" # API key miễn phí của TheSportsDB, có thể đổi thành "123" nếu key này nghẽn

TARGET_LEAGUES = {
    "English Premier League": "Premier League",
    "Italian Serie A": "Serie A",
    "German Bundesliga": "Bundesliga",
    "Spanish La Liga": "La Liga",
    "French Ligue 1": "Ligue 1",
    "UEFA Champions League": "UEFA Champions League",
    "UEFA Europa League": "UEFA Europa League",
    "UEFA Europa Conference League": "UEFA Europa Conference League",
    "UEFA Conference League": "UEFA Europa Conference League"
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
}

LEAGUE_ORDER = list(LEAGUE_VN_NAME.keys())

LEAGUE_BROADCAST_DEFAULT = {
    "Premier League": "Sky Sports • TNT Sports",
    "Serie A": "DAZN • Sky Sport Italia",
    "Bundesliga": "Sky Sport • DAZN",
    "La Liga": "DAZN • Movistar",
    "Ligue 1": "beIN Sports • Canal+",
    "UEFA Champions League": "TNT Sports • beIN Sports",
    "UEFA Europa League": "TNT Sports • beIN Sports",
    "UEFA Europa Conference League": "TNT Sports • beIN Sports",
}

# Fallback nếu api lookuptv trả về rỗng cho trận đấu đó
FALLBACK_KEYWORDS = {
    "Premier League": ["sky sports premier", "tnt sports 1", "tnt sports 2", "astro supersport"],
    "Serie A": ["sky sport italia", "dazn serie a", "bein sports serie a"],
    "Bundesliga": ["sky sport bundesliga", "dazn bundesliga"],
    "La Liga": ["dazn la liga", "movistar la liga", "supersport laliga"],
    "Ligue 1": ["bein sports ligue 1", "canal+ ligue 1"],
    "UEFA Champions League": ["tnt sports champions", "sky sports champions", "arena sport champions"],
    "UEFA Europa League": ["tnt sports europa", "sky sports europa"],
    "UEFA Europa Conference League": ["bein conference", "tnt conference"],
}

# Từ khóa bỏ qua khi match kênh để tránh nhiễu
IGNORE_WORDS = {'hd', 'fhd', 'uhd', '4k', 'tv', 'sports', 'sport', 'channel', 'network', 'ch', 'live'}

# ================== HELPER ==================
def fetch_text(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; EuroVN/5.0)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")

def is_healthy(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "VLC/3.0.18"})
        with urllib.request.urlopen(req, timeout=4) as r:
            return r.getcode() < 400
    except:
        return False

def normalize(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return " ".join(c for c in s if unicodedata.category(c) != "Mn")

def vn_time(utc_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
        return dt.astimezone(TIMEZONE).strftime("%-I:%M %p")
    except:
        return utc_iso

def is_low_resolution(res: str, ch_name: str) -> bool:
    name_lower = ch_name.lower()
    if 'sd' in name_lower or ' sd' in name_lower or 'sd ' in name_lower:
        return True
    if not res:
        return True
    res = res.lower()
    if 'sd' in res or any(x in res for x in ['360p','480p','576p','360','480','576','low']):
        return True
    nums = re.findall(r'\d+', res)
    return any(int(n) < 720 for n in nums)

# ================== FETCH THESPORTSDB ==================
def fetch_tv_channels(event_id: str) -> list:
    url = f"https://www.thesportsdb.com/api/v1/json/{TSDB_API_KEY}/lookuptv.php?id={event_id}"
    try:
        time.sleep(0.1)  # Giãn nhịp để tránh bị Rate Limit
        data = json.loads(fetch_text(url))
        tvs = data.get("tvevents") or data.get("tvnetworks") or []
        channels = [tv.get("strTVStation") for tv in tvs if tv.get("strTVStation")]
        return list(set(channels))
    except:
        return []

def is_tv_match(tv_name: str, m3u_name: str) -> bool:
    """ Khớp thông minh kênh TheSportsDB (VD: Viaplay Sports 2 UK) vào kênh M3U """
    tv = normalize(tv_name).replace('-', ' ').replace('+', ' ').strip()
    m3u = normalize(m3u_name).replace('-', ' ').replace('+', ' ').replace('|', ' ').replace(':', ' ').strip()
    
    # Loại bỏ các đuôi quốc gia TheSportsDB thường chèn thêm vào cuối
    suffixes = r'\s+(uk|ie|cz|hr|tr|se|cn|ru|bg|pt|ch|au|sg|my|th|za|nz|us|fr|es|it|de|ar|br|nl|be|dk|no|fi|arabia|qatar|thailand|malaysia|singapore|australia|portugal|russia)$'
    tv_clean = re.sub(suffixes, '', tv).strip()
    
    # Bóc tách từ khóa cốt lõi (VD: ["viaplay", "2"])
    words = [w for w in tv_clean.split() if w not in IGNORE_WORDS]
    
    # Nếu kênh chỉ có 1 từ quá ngắn gọn, dùng check cụm dính liền
    if not words: 
        return tv_clean.replace(" ", "") in m3u.replace(" ", "")
        
    m3u_words = set(m3u.split())
    
    # Điều kiện tiên quyết: Mọi từ khóa lõi của TheSportsDB phải nằm trong chuỗi của M3U
    if all(w in m3u_words for w in words):
        return True
        
    # Xử lý trường hợp kênh bị dính chữ trong M3U (VD: tv_clean="DAZN LaLiga", m3u="DAZNLALIGA")
    if tv_clean.replace(" ", "") in m3u.replace(" ", ""):
        return True
        
    return False

# ================== M3U PARSER ==================
def parse_m3u(content):
    channels, current, extra = [], {}, []
    for line in content.split('\n'):
        line = line.strip()
        if not line: continue
        if line.startswith('#EXTINF'):
            if current.get('name') and current.get('url'):
                if extra: current['extra'] = extra[:]
                channels.append(current)
            current, extra = {}, []
            params = re.findall(r'([a-zA-Z-]+)="([^"]*)"', line)
            current['params'] = {k.lower(): v for k,v in params}
            name_part = line.split(',', 1)
            current['name'] = unquote(name_part[1].strip()) if len(name_part)>1 else "Unknown"
        elif line.startswith('http'):
            if current:
                current['url'] = line
                if extra: current['extra'] = extra[:]
                channels.append(current)
                current, extra = {}, []
        elif line.startswith('#EXTVLCOPT') or line.startswith('#EXTGRP'):
            extra.append(line)
    if current.get('name') and current.get('url'):
        if extra: current['extra'] = extra[:]
        channels.append(current)
    return channels

# ================== MAIN ==================
def main():
    start = time.time()
    vn_now = datetime.now(TIMEZONE)
    print("🔄 Bắt đầu lấy dữ liệu chuẩn xác từ TheSportsDB...")

    # === BƯỚC 1: XÂY DỰNG SCHEDULE ===
    dates = [(vn_now.date() + timedelta(i), (vn_now.date() + timedelta(i)).strftime("%Y%m%d")) for i in range(DAYS_AHEAD)]
    schedule = {ds: {"date": dt.strftime("%A, %d/%m"), "games": []} for dt, ds in dates}

    for dt, ds in dates:
        date_str_api = dt.strftime("%Y-%m-%d")
        print(f"📥 Đang lấy lịch thi đấu ngày {date_str_api}...")
        url = f"https://www.thesportsdb.com/api/v1/json/{TSDB_API_KEY}/eventsday.php?d={date_str_api}&s=Soccer"
        try:
            data = json.loads(fetch_text(url))
            events = data.get("events")
            if not events: continue
        except Exception as e:
            print(f"  Lỗi API ngày {date_str_api}: {e}")
            continue

        for ev in events:
            league = ev.get("strLeague")
            if league not in TARGET_LEAGUES:
                continue

            match = f"{ev.get('strHomeTeam')} vs {ev.get('strAwayTeam')}"
            event_id = ev.get("idEvent")
            time_utc = ev.get("strTimestamp")
            
            if not time_utc:
                if ev.get("dateEvent") and ev.get("strTime"):
                    time_utc = f"{ev.get('dateEvent')}T{ev.get('strTime')}Z"
                else:
                    continue

            status = ev.get("strStatus", "")
            if status in ("Postponed", "Cancelled", "Suspended"):
                continue

            # API 2: Lấy các đài phát sóng chính xác
            channels = fetch_tv_channels(event_id)
            league_normalized = TARGET_LEAGUES[league]
            
            source_display = " • ".join(channels[:4]) + ("..." if len(channels)>4 else "") if channels else LEAGUE_BROADCAST_DEFAULT.get(league_normalized, "")

            schedule[ds]["games"].append({
                "league": league_normalized,
                "time": vn_time(time_utc),
                "match": match,
                "source": source_display,
                "kick_utc": time_utc,
                "tv_channels": channels
            })

    # Dedup & Sort games
    for ds, day in schedule.items():
        seen = {}
        deduped = []
        for g in day["games"]:
            key = normalize(g["match"]) + "|" + g["time"]
            if key not in seen:
                seen[key] = g
                deduped.append(g)
        day["games"] = deduped
        day["games"].sort(key=lambda g: (LEAGUE_ORDER.index(g["league"]) if g["league"] in LEAGUE_ORDER else 99, g.get("time","")))

    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump({"updated": vn_now.strftime("%Y-%m-%d %H:%M VN"), "days": schedule}, f, indent=2, ensure_ascii=False)

    print(f"✅ Đã lưu schedule.json: {sum(len(d['games']) for d in schedule.values())} trận có lịch.")

    # === BƯỚC 2: M3U PARSER & MATCHING CHÍNH XÁC ===
    print("📥 Đang tải và phân tích danh sách kênh M3U...")
    m3u_links = [line.strip() for line in open(M3U_LIST_FILE, encoding='utf-8') if line.strip().startswith('http')]
    
    all_ch = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(lambda u: (u, fetch_text(u)), url): url for url in m3u_links}
        for fut in as_completed(futures):
            try:
                _, content = fut.result()
                all_ch.extend(parse_m3u(content))
            except: continue

    unique_ch = list({ch['url']: ch for ch in all_ch if ch.get('url')}.values())
    
    print("🔍 Đang gán ghép kênh với từng trận đấu...")
    matched_channels = []

    for date_str, day in schedule.items():
        for g in day.get("games", []):
            try:
                game_dt = datetime.fromisoformat(g["kick_utc"].replace("Z", "+00:00")).astimezone(TIMEZONE)
                if game_dt < vn_now: continue
            except: continue

            tvs = g.get("tv_channels", [])
            fallbacks = FALLBACK_KEYWORDS.get(g["league"], [])

            for ch in unique_ch:
                res_match = re.search(r'(\d{3,4}[pP]|\d+K|HD|SD)', ch.get('name',''))
                res = res_match.group(0).upper() if res_match else ""
                if is_low_resolution(res, ch['name']): continue
                ch['resolution'] = res

                matched = False
                matched_tv = ""

                # Ưu tiên thuật toán khớp chính xác TheSportsDB
                for tv in tvs:
                    if is_tv_match(tv, ch['name']):
                        matched = True
                        matched_tv = tv
                        break
                
                # Nếu TheSportsDB không có dữ liệu kênh cho trận này -> Dùng Fallback mặc định
                if not matched and not tvs:
                    name_lower = ch['name'].lower()
                    for kw in fallbacks:
                        if kw in name_lower:
                            matched = True
                            matched_tv = kw.title()
                            break

                if matched:
                    matched_channels.append({
                        "game": g,
                        "game_dt": game_dt,
                        "channel": ch,
                        "tv_station": matched_tv
                    })

    # === BƯỚC 3: CHECK HEALTH MỤC TIÊU ===
    print(f"📡 Tìm thấy {len(matched_channels)} mục tiêu tiềm năng. Bắt đầu Check Health...")
    
    # Chỉ ping những URL đã match thay vì quét cả list M3U, siêu nhanh!
    urls_to_check = list(set(mc["channel"]["url"] for mc in matched_channels))
    valid_urls = set()

    with ThreadPoolExecutor(max_workers=20) as ex:
        fut_to_url = {ex.submit(is_healthy, url): url for url in urls_to_check}
        for fut in as_completed(fut_to_url):
            if fut.result():
                valid_urls.add(fut_to_url[fut])

    # === BƯỚC 4: XUẤT LIVE_SCHEDULE.M3U ===
    live_events = []
    for mc in matched_channels:
        if mc["channel"]["url"] in valid_urls:
            g = mc["game"]
            display_name = f"{g['time']} | {g['league']} - {g['match']} ({mc['tv_station']})"
            live_events.append({
                "datetime": mc["game_dt"],
                "name": display_name,
                "channel": mc["channel"],
                "league": g["league"]
            })
            
    live_events.sort(key=lambda x: x["datetime"])

    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ev in live_events:
            ch = ev["channel"]
            group_vn = LEAGUE_VN_NAME.get(ev["league"], "Lịch trực tiếp")
            tvg_id = ch['params'].get('tvg-id', '')
            tvg_logo = ch['params'].get('tvg-logo', '')
            extinf = f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{group_vn}"'
            if tvg_logo: extinf += f' tvg-logo="{tvg_logo}"'
            extinf += f',{ev["name"]}'
            
            f.write(extinf + "\n")
            if 'extra' in ch:
                for line in ch['extra']:
                    if not line.startswith('#EXTINF'): f.write(line + "\n")
            f.write(ch['url'] + "\n")

    print(f"\n🎉 HOÀN THÀNH!")
    print(f"   • Quét kênh chính xác: Nhờ API TheSportsDB")
    print(f"   • Tổng số kênh M3U được chọn ra: {len(live_events)} kênh (100% Khớp & Live)")
    print(f"   • Thời gian chạy thực tế: {time.time() - start:.1f}s")

if __name__ == "__main__":
    main()
