"""
euro_vn_full_schedule_live.py
================================
BẢN TỐI ƯU SIÊU NHANH - CHẠY TRONG 2-4 PHÚT TRÊN GITHUB
- Chỉ giữ ngay từ đầu những kênh có tên chứa Sky/TNT/beIN/Arena/Astro/Now/DAZN...
- Không kiểm tra sức khỏe hàng nghìn kênh rác nữa
- 1 trận có nhiều kênh → giữ nguyên tất cả
- Chỉ bỏ kênh lỗi + SD/low resolution
- Output: schedule.json + live_schedule.m3u (group: "Lịch trực tiếp")

Copy nguyên file này thay thế file cũ → commit → chạy lại workflow!
"""

import json
import re
import unicodedata
import urllib.request
import urllib.error
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

ESPN_LEAGUES = {
    "eng.1": "Premier League",
    "ita.1": "Serie A",
    "ger.1": "Bundesliga",
    "esp.1": "La Liga",
    "fra.1": "Ligue 1",
    "uefa.champions": "UEFA Champions League",
    "uefa.europa": "UEFA Europa League",
}

LEAGUE_BROADCAST_DEFAULT = {
    "Premier League": "Sky Sports • TNT Sports • beIN Sports • Astro SuperSport",
    "Serie A": "DAZN • Sky Sport Italia • beIN Sports",
    "Bundesliga": "Sky Sport Deutschland • DAZN",
    "La Liga": "DAZN • Movistar • beIN Sports",
    "Ligue 1": "beIN Sports • Canal+ • DAZN",
    "UEFA Champions League": "TNT Sports • Sky Sports • beIN Sports • Arena Sport",
    "UEFA Europa League": "TNT Sports • Sky Sports • beIN Sports",
    "UEFA Europa Conference League": "beIN Sports • TNT Sports • Sky Sports",
}

# Từ khóa broadcaster để lọc NGAY TỪ ĐẦU (tối ưu tốc độ)
BROADCAST_KEYWORDS = {
    "sky": ["sky sport", "skysports", "sky sports"],
    "tnt": ["tnt sport", "tntsports", "bt sport"],
    "bein": ["bein sport", "beinsports", "bein"],
    "arena": ["arena sport", "arenasport"],
    "astro": ["astro", "supersport"],
    "now": ["now sport", "nowsports", "now tv"],
    "dazn": ["dazn"],
}

LEAGUE_ORDER = ["UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
                "Premier League", "Serie A", "Bundesliga", "La Liga", "Ligue 1"]

# ================== HELPER (urllib thuần) ==================
def fetch_text(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; EuroVN/3.0)"})
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

def is_real_match(title: str) -> bool:
    bad = ["golazo", "espn fc", "futbol picante", "pre-show", "post-show", "halftime"]
    return not any(k in title.lower() for k in bad)

def vn_time(utc_iso: str) -> str:
    dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
    return dt.astimezone(TIMEZONE).strftime("%-I:%M %p")

def is_low_resolution(res: str) -> bool:
    if not res: return False
    res = res.lower()
    if 'sd' in res or any(x in res for x in ['360p','480p','576p','360','480','576','low']):
        return True
    nums = re.findall(r'\d+', res)
    return any(int(n) < 720 for n in nums)

def get_keywords(source: str):
    if not source: return set()
    cleaned = re.sub(r'\([^)]+\)', '', source.lower())
    parts = [p.strip() for p in cleaned.split('•')]
    kws = set()
    for p in parts:
        for variants in BROADCAST_KEYWORDS.values():
            if any(v in p for v in variants):
                kws.add(variants[0])
        kws.update(re.findall(r'\b\w{4,}\b', p))
    return kws

# ================== FETCH ESPN + CONFERENCE ==================
def fetch_espn_league_day(slug: str, name: str, date_str: str):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={date_str}"
    try:
        data = json.loads(fetch_text(url))
    except Exception as e:
        print(f"  Lỗi API {name}: {e}")
        return []
    games = []
    for event in data.get("events", []):
        try:
            comp = event["competitions"][0]
            teams = comp["competitors"]
            if len(teams) < 2: continue
            home = next((t for t in teams if t.get("homeAway")=="home"), teams[0])
            away = next((t for t in teams if t.get("homeAway")=="away"), teams[1])
            match = f"{home['team']['displayName']} vs {away['team']['displayName']}"
            if not is_real_match(match): continue

            raw = event.get("date")
            if not raw: continue
            if datetime.fromisoformat(raw.replace("Z","+00:00")).astimezone(TIMEZONE).strftime("%Y%m%d") != date_str:
                continue

            status = event["status"]["type"]["name"]
            if any(s in status.upper() for s in ["POSTPONED","CANCELED","DELAYED","SUSPENDED"]):
                games.append({"league":name, "time":status.replace("STATUS_","").title(), "match":match, "source":"", "kick_utc":raw})
                continue

            source = LEAGUE_BROADCAST_DEFAULT.get(name, "Sky Sports • beIN Sports")
            games.append({"league":name, "time":vn_time(raw), "match":match, "source":source, "kick_utc":raw})
        except:
            continue
    return games

def fetch_scoreboard_league(date_str: str):
    url = f"https://www.espn.com/soccer/scoreboard/_/date/{date_str}"
    try:
        html = fetch_text(url)
    except Exception as e:
        print(f"  Scrape Conference lỗi: {e}")
        return []
    games = []
    start = html.find('>UEFA Europa Conference League<')
    if start == -1: return games
    section = html[start:html.find('Card__Header__Title', start+100) or len(html)]
    pos = 0
    while True:
        idx = section.find('ScoreboardScoreCell__Overview', pos)
        if idx == -1: break
        div_start = section.rfind('<div', 0, idx)
        next_idx = section.find('ScoreboardScoreCell__Overview', idx+30)
        chunk = section[div_start:next_idx if next_idx != -1 else len(section)]

        t_idx = chunk.find('ScoreCell__Time')
        time_val = chunk[chunk.find('>', t_idx)+1:chunk.find('<', chunk.find('>', t_idx)+1)].strip() if t_idx != -1 else ""

        networks = []
        n_pos = 0
        while True:
            n_idx = chunk.find('ScoreCell__NetworkItem', n_pos)
            if n_idx == -1: break
            net = chunk[chunk.find('>', n_idx)+1:chunk.find('<', chunk.find('>', n_idx)+1)].strip()
            if net: networks.append(net)
            n_pos = n_idx + 30

        teams = []
        tp = 0
        while len(teams) < 2:
            t_idx = chunk.find('ScoreCell__TeamName--shortDisplayName', tp)
            if t_idx == -1: break
            team = chunk[chunk.find('>', t_idx)+1:chunk.find('<', chunk.find('>', t_idx)+1)].strip()
            if team: teams.append(team)
            tp = t_idx + 50

        pos = next_idx if next_idx != -1 else len(section)
        if len(teams) < 2 or not time_val: continue

        source = " • ".join(networks) if networks else LEAGUE_BROADCAST_DEFAULT["UEFA Europa Conference League"]
        games.append({
            "league": "UEFA Europa Conference League",
            "time": time_val if re.match(r'^\d', time_val) else time_val.title(),
            "match": f"{teams[0]} vs {teams[1]}",
            "source": source
        })
    return games

# ================== M3U PARSER (có lọc broadcaster ngay) ==================
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

# ================== MAIN - SIÊU NHANH ==================
def main():
    start = time.time()
    vn_now = datetime.now(TIMEZONE)
    print("🔄 Bắt đầu (bản tối ưu - chỉ 2-4 phút)...")

    # === BƯỚC 1: schedule.json ===
    dates = [(d, d.strftime("%Y%m%d")) for d in [datetime.now(TIMEZONE).date() + timedelta(i) for i in range(DAYS_AHEAD)]]
    schedule = {ds: {"date": dt.strftime("%A, %d/%m"), "games": []} for dt, ds in dates}

    for slug, name in ESPN_LEAGUES.items():
        print(f"Fetching {name}...")
        for _, ds in dates:
            schedule[ds]["games"].extend(fetch_espn_league_day(slug, name, ds))

    print("Fetching UEFA Europa Conference League...")
    for _, ds in dates:
        schedule[ds]["games"].extend(fetch_scoreboard_league(ds))

    # Dedup + prune
    for ds, day in schedule.items():
        seen = {}
        deduped = []
        for g in day["games"]:
            key = normalize(g["match"]) + "|" + g["time"]
            if key not in seen:
                seen[key] = g
                deduped.append(g)
        day["games"] = deduped
        if ds == dates[0][1]:
            day["games"] = [g for g in day["games"] if not g["time"].strip().startswith(("Postponed","Canceled","Delayed","Suspended"))]

    for day in schedule.values():
        day["games"].sort(key=lambda g: (LEAGUE_ORDER.index(g["league"]) if g["league"] in LEAGUE_ORDER else 99, g.get("time","")))

    output = {"updated": vn_now.strftime("%Y-%m-%d %H:%M VN"), "days": schedule}
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"✅ schedule.json: {sum(len(d['games']) for d in schedule.values())} trận")

    # === BƯỚC 2: live_schedule.m3u (TỐI ƯU) ===
    print("📥 Đang tải M3U và lọc kênh thể thao...")
    m3u_links = [line.strip() for line in open(M3U_LIST_FILE, encoding='utf-8') if line.strip().startswith('http')]

    all_ch = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(lambda u: (u, fetch_text(u)), url): url for url in m3u_links}
        for fut in as_completed(futures):
            try:
                _, content = fut.result()
                chs = parse_m3u(content)
                for ch in chs:
                    name_lower = ch.get('name', '').lower()
                    # LỌC NGAY TỪ ĐÂY - chỉ giữ kênh broadcaster
                    if not any(any(var in name_lower for var in variants) for variants in BROADCAST_KEYWORDS.values()):
                        continue
                    res_match = re.search(r'(\d{3,4}[pP]|\d+K|HD|SD)', ch.get('name',''))
                    res = res_match.group(0).upper() if res_match else ""
                    if is_low_resolution(res): continue
                    ch['resolution'] = res
                    all_ch.append(ch)
            except:
                continue

    print(f"   → Đã lọc được {len(all_ch)} kênh thể thao tiềm năng (Sky/TNT/beIN...)")

    # Unique + health check (chỉ trên vài trăm kênh)
    unique = {ch['url']: ch for ch in all_ch if ch.get('url')}
    unique_ch = list(unique.values())

    print("🔍 Kiểm tra kênh live (chỉ vài trăm kênh)...")
    valid_ch = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        fut_to_ch = {ex.submit(is_healthy, ch['url']): ch for ch in unique_ch}
        for fut in as_completed(fut_to_ch):
            if fut.result():
                valid_ch.append(fut_to_ch[fut])

    # Thu thập trận + kênh (giữ nhiều kênh cho 1 trận)
    live_events = []
    for date_str, day in schedule.items():
        for g in day.get("games", []):
            try:
                t_str = g["time"].strip()
                if not re.match(r'^\d', t_str): continue
                game_dt = datetime.strptime(t_str, "%I:%M %p").replace(
                    year=int(date_str[:4]), month=int(date_str[4:6]), day=int(date_str[6:])).replace(tzinfo=TIMEZONE)
                if game_dt < vn_now: continue
            except:
                continue

            kws = get_keywords(g.get("source", ""))
            if not kws: continue

            matching = [ch for ch in valid_ch if any(kw in ch['name'].lower() for kw in kws if len(kw)>=3)]
            for ch in matching:
                short_src = g["source"].split('•')[0].strip() if g.get("source") else ""
                display_name = f"{g['time']} | {g['league']} - {g['match']} ({short_src})"
                live_events.append({
                    "datetime": game_dt,
                    "name": display_name,
                    "channel": ch,
                    "league": g["league"]
                })

    live_events.sort(key=lambda x: x["datetime"])

    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ev in live_events:
            ch = ev["channel"]
            tvg_id = ch['params'].get('tvg-id', '')
            tvg_logo = ch['params'].get('tvg-logo', '')
            extinf = f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="Lịch trực tiếp"'
            if tvg_logo:
                extinf += f' tvg-logo="{tvg_logo}"'
            extinf += f',{ev["name"]}'
            f.write(extinf + "\n")
            if 'extra' in ch:
                for line in ch['extra']:
                    if not line.startswith('#EXTINF'):
                        f.write(line + "\n")
            f.write(ch['url'] + "\n")

    total_live = len(live_events)
    elapsed = time.time() - start
    print(f"\n🎉 HOÀN THÀNH SIÊU NHANH!")
    print(f"   • schedule.json: {sum(len(d['games']) for d in schedule.values())} trận")
    print(f"   • live_schedule.m3u: {total_live} kênh livestream")
    print(f"   • Thời gian: {elapsed:.1f}s")

if __name__ == "__main__":
    main()
