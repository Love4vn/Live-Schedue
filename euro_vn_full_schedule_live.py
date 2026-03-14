"""
euro_vn_full_schedule_live.py
================================
BẢN NÂNG CẤP FOTMOB - LẤY KÊNH CHUẨN XÁC
- Lấy lịch: Premier League, Serie A, Bundesliga, La Liga, Ligue 1, UCL, UEL, Conference
- Nguồn: FotMob API (Miễn phí & Chính xác hơn ESPN/TheSportsDB)
- Broadcaster: Lấy danh sách kênh thực tế phát sóng từng trận
- Không cần API Key, không cần pip install
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

# Mapping ID FotMob sang tên giải
FOTMOB_LEAGUES = {
    47: "Premier League",
    87: "La Liga",
    55: "Serie A",
    54: "Bundesliga",
    53: "Ligue 1",
    42: "UEFA Champions League",
    73: "UEFA Europa League",
    9231: "UEFA Europa Conference League"
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

# Từ khóa lọc kênh từ M3U (Giữ nguyên từ code cũ của bạn)
BROADCAST_KEYWORDS = {
    "Premier League": ["sky sports premier", "tnt sports 1", "tnt sports 2", "bein sports 1", "bein 1", "astro supersport", "now tv premier"],
    "Serie A": ["sky sport italia", "dazn serie a", "bein sports serie a"],
    "Bundesliga": ["sky sport bundesliga", "sky sport deutschland", "dazn bundesliga"],
    "La Liga": ["dazn la liga", "movistar la liga", "bein sports la liga"],
    "Ligue 1": ["bein sports ligue 1", "canal+ ligue 1", "bein ligue"],
    "UEFA Champions League": ["tnt sports champions", "sky sports champions", "bein champions", "arena sport champions"],
    "UEFA Europa League": ["tnt sports europa", "sky sports europa", "bein europa"],
    "UEFA Europa Conference League": ["bein conference", "tnt conference"],
}

LEAGUE_ORDER = list(LEAGUE_VN_NAME.keys())

# ================== HELPER ==================
def fetch_json(url: str, timeout: int = 15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

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
    # FotMob trả về dạng: 2024-05-19T15:00:00.000Z
    dt = datetime.strptime(utc_iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(TIMEZONE).strftime("%-I:%M %p")

def is_low_resolution(res: str, ch_name: str) -> bool:
    name_lower = ch_name.lower()
    if any(x in name_lower for x in [' sd', 'sd ', '(sd)']): return True
    if not res: return False
    res = res.lower()
    if 'sd' in res or any(x in res for x in ['360p','480p','576p']): return True
    return False

# ================== FOTMOB LOGIC ==================
def get_match_broadcasters(match_id):
    """Lấy danh sách kênh truyền hình thực tế của trận đấu"""
    url = f"https://www.fotmob.com/api/matchDetails?matchId={match_id}"
    try:
        data = fetch_json(url)
        broadcasters = []
        # Lấy từ mục broadcast -> broadcasters (nhóm theo quốc gia)
        bc_data = data.get("content", {}).get("broadcast", {}).get("broadcasters", {})
        for country in bc_data:
            for channel in bc_data[country]:
                broadcasters.append(channel.get("name"))
        return " • ".join(list(set(broadcasters))) if broadcasters else ""
    except:
        return ""

def fetch_fotmob_day(date_str):
    """Lấy toàn bộ trận đấu trong 1 ngày và lọc theo giải mong muốn"""
    url = f"https://www.fotmob.com/api/matches?date={date_str}"
    try:
        data = fetch_json(url)
        day_games = []
        
        # FotMob trả về danh sách leagues, mỗi league có danh sách matches
        for league in data.get("leagues", []):
            l_id = league.get("id")
            if l_id in FOTMOB_LEAGUES:
                l_name = FOTMOB_LEAGUES[l_id]
                for m in league.get("matches", []):
                    # Chỉ lấy trận chưa diễn ra hoặc đang diễn ra
                    if not m.get("status", {}).get("cancelled"):
                        match_name = f"{m['home']['name']} vs {m['away']['name']}"
                        kick_off = m['status']['utcTime']
                        
                        day_games.append({
                            "id": m['id'],
                            "league": l_name,
                            "time": vn_time(kick_off),
                            "match": match_name,
                            "kick_utc": kick_off
                        })
        return day_games
    except Exception as e:
        print(f"  Lỗi FotMob ngày {date_str}: {e}")
        return []

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
def main():
    start_time = time.time()
    vn_now = datetime.now(TIMEZONE)
    print(f"🔄 Bắt đầu chạy FotMob Edition [{vn_now.strftime('%H:%M:%S')}]")

    # === BƯỚC 1: Lấy lịch trận đấu ===
    dates = [(vn_now.date() + timedelta(i)).strftime("%Y%m%d") for i in range(DAYS_AHEAD)]
    all_games = []
    for ds in dates:
        print(f"  Đang quét lịch ngày {ds}...")
        all_games.extend(fetch_fotmob_day(ds))

    # Lấy thông tin kênh chi tiết cho từng trận (Dùng Thread để chạy nhanh)
    print(f"  Đang lấy thông tin kênh cho {len(all_games)} trận...")
    final_games = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_game = {executor.submit(get_match_broadcasters, g['id']): g for g in all_games}
        for future in as_completed(future_to_game):
            game = future_to_game[future]
            game['source'] = future.result()
            final_games.append(game)

    # Phân bổ vào schedule.json
    schedule_data = {}
    for ds in dates:
        dt_obj = datetime.strptime(ds, "%Y%m%d")
        day_games = [g for g in final_games if datetime.strptime(g['kick_utc'][:10], "%Y-%m-%d").strftime("%Y%m%d") == ds]
        day_games.sort(key=lambda x: (LEAGUE_ORDER.index(x["league"]) if x["league"] in LEAGUE_ORDER else 99, x["time"]))
        schedule_data[ds] = {
            "date": dt_obj.strftime("%A, %d/%m"),
            "games": day_games
        }

    output = {"updated": vn_now.strftime("%Y-%m-%d %H:%M VN"), "days": schedule_data}
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"✅ Đã lưu {SCHEDULE_FILE}")

    # === BƯỚC 2: Tạo Live M3U (Giữ nguyên logic lọc M3U_list của bạn) ===
    print("📥 Đang lọc kênh từ M3U_list.txt...")
    try:
        m3u_links = [line.strip() for line in open(M3U_LIST_FILE, encoding='utf-8') if line.strip().startswith('http')]
    except:
        print("❌ Không tìm thấy M3U_list.txt")
        return

    all_ch = []
    def process_m3u_url(url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "VLC/3.0.18"})
            with urllib.request.urlopen(req, timeout=10) as r:
                content = r.read().decode("utf-8")
                chs = parse_m3u(content)
                local_found = []
                for ch in chs:
                    name_lower = ch.get('name', '').lower()
                    if is_low_resolution("", ch['name']): continue
                    for league, keywords in BROADCAST_KEYWORDS.items():
                        if any(kw in name_lower for kw in keywords):
                            ch['league'] = league
                            local_found.append(ch)
                            break
                return local_found
        except: return []

    with ThreadPoolExecutor(max_workers=15) as ex:
        futures = [ex.submit(process_m3u_url, u) for u in m3u_links]
        for fut in as_completed(futures):
            all_ch.extend(fut.result())

    # Kiểm tra link sống
    unique_ch = list({ch['url']: ch for ch in all_ch}.values())
    print(f"🔍 Kiểm tra {len(unique_ch)} kênh tìm thấy...")
    valid_ch = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        fut_to_ch = {ex.submit(is_healthy, ch['url']): ch for ch in unique_ch}
        for fut in as_completed(fut_to_ch):
            if fut.result(): valid_ch.append(fut_to_ch[fut])

    # Khớp trận với kênh
    live_events = []
    for g in final_games:
        try:
            game_dt = datetime.strptime(g['kick_utc'][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=ZoneInfo("UTC")).astimezone(TIMEZONE)
            if game_dt < (vn_now - timedelta(hours=2)): continue # Bỏ trận đã kết thúc
            
            # Lọc kênh khớp với giải của trận đấu
            matching_ch = [ch for ch in valid_ch if ch['league'] == g['league']]
            for ch in matching_ch:
                display_name = f"{g['time']} | {g['league']} - {g['match']}"
                if g['source']: display_name += f" ({g['source'].split(' • ')[0]})"
                
                live_events.append({
                    "datetime": game_dt,
                    "name": display_name,
                    "channel": ch,
                    "league": g["league"]
                })
        except: continue

    live_events.sort(key=lambda x: x["datetime"])

    # Xuất file M3U
    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ev in live_events:
            ch = ev["channel"]
            group = LEAGUE_VN_NAME.get(ev["league"], "Lịch trực tiếp")
            tvg_id = ch['params'].get('tvg-id', '')
            logo = ch['params'].get('tvg-logo', '')
            f.write(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{logo}" group-title="{group}",{ev["name"]}\n')
            if 'extra' in ch:
                for line in ch['extra']: f.write(line + "\n")
            f.write(ch['url'] + "\n")

    print(f"\n🎉 HOÀN THÀNH trong {time.time() - start_time:.1f}s!")
    print(f"   • Trận đấu tìm thấy: {len(final_games)}")
    print(f"   • Luồng Live khả dụng: {len(live_events)}")

if __name__ == "__main__":
    main()
