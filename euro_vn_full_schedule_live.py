"""
euro_vn_full_schedule_live.py
================================
BẢN HOÀN CHỈNH CUỐI CÙNG - CHẠY TRÊN GITHUB (không cần pip)
- Lấy lịch: Premier League, Serie A, Bundesliga, La Liga, Ligue 1, UCL, UEL, Conference
- Thời gian: giờ Việt Nam (Asia/Ho_Chi_Minh)
- Broadcaster: lọc CHÍNH XÁC theo giải (Sky Sports Premier League, TNT Sports 1, beIN 1...)
- Loại triệt để: kênh SD, low resolution, kênh không khớp
- 1 trận có nhiều kênh → giữ nguyên tất cả
- Phân nhóm trong live_schedule.m3u: 
  • Giải Ngoại Hạng Anh
  • Giải Đức
  • Giải Ý
  • Giải Tây Ban Nha
  • Giải Pháp
  • UEFA Champions League
  • UEFA Europa League
  • UEFA Conference League
- Output: schedule.json + live_schedule.m3u
- Chạy siêu nhanh (2-4 phút)

Đặt file này + M3U_list.txt vào repo → commit → workflow tự chạy!
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

# Từ khóa CHÍNH XÁC theo từng giải (lọc chặt để tránh nhầm kênh)
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

# ================== HELPER ==================
def fetch_text(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; EuroVN/4.0)"})
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

# ================== FETCH ESPN ==================
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

# ================== SCRAPE CONFERENCE LEAGUE ==================
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
    start = time.time()
    vn_now = datetime.now(TIMEZONE)
    print("🔄 Bắt đầu chạy bản hoàn chỉnh...")

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

    # Dedup + prune today
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

    # === BƯỚC 2: live_schedule.m3u (chính xác + phân nhóm) ===
    print("📥 Đang lọc kênh chính xác theo giải...")
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
                    res_match = re.search(r'(\d{3,4}[pP]|\d+K|HD|SD)', ch.get('name',''))
                    res = res_match.group(0).upper() if res_match else ""
                    if is_low_resolution(res, ch['name']): continue

                    # Chỉ giữ kênh khớp chính xác với giải
                    for league, keywords in BROADCAST_KEYWORDS.items():
                        if any(kw in name_lower for kw in keywords):
                            ch['league'] = league
                            ch['resolution'] = res
                            all_ch.append(ch)
                            break
            except:
                continue

    unique = {ch['url']: ch for ch in all_ch if ch.get('url')}
    unique_ch = list(unique.values())

    print("🔍 Kiểm tra kênh live...")
    valid_ch = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        fut_to_ch = {ex.submit(is_healthy, ch['url']): ch for ch in unique_ch}
        for fut in as_completed(fut_to_ch):
            if fut.result():
                valid_ch.append(fut_to_ch[fut])

    print(f"   → Còn {len(valid_ch)} kênh chất lượng cao & khớp broadcaster")

    # Thu thập trận + kênh
    live_events = []
    for date_str, day in schedule.items():
        for g in day.get("games", []):
            try:
                t_str = g["time"].strip()
                if not re.match(r'^\d', t_str): continue
                game_dt = datetime.strptime(t_str, "%I:%M %p").replace(
                    year=int(date_str[:4]), month=int(date_str[4:6]), day=int(date_str[6:])).replace(tzinfo=TIMEZONE)
                if game_dt < vn_now: continue

                kws = BROADCAST_KEYWORDS.get(g["league"], [])
                matching = [ch for ch in valid_ch if ch.get('league') == g["league"] and any(k in ch['name'].lower() for k in kws)]
                for ch in matching:
                    short_src = g["source"].split('•')[0].strip() if g.get("source") else ""
                    display_name = f"{g['time']} | {g['league']} - {g['match']} ({short_src})"
                    live_events.append({
                        "datetime": game_dt,
                        "name": display_name,
                        "channel": ch,
                        "league": g["league"]
                    })
            except:
                continue

    live_events.sort(key=lambda x: x["datetime"])

    # Xuất M3U với nhóm riêng theo giải
    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ev in live_events:
            ch = ev["channel"]
            group_vn = LEAGUE_VN_NAME.get(ev["league"], "Lịch trực tiếp")
            tvg_id = ch['params'].get('tvg-id', '')
            tvg_logo = ch['params'].get('tvg-logo', '')
            extinf = f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{group_vn}"'
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
    print(f"\n🎉 HOÀN THÀNH!")
    print(f"   • schedule.json: {sum(len(d['games']) for d in schedule.values())} trận")
    print(f"   • live_schedule.m3u: {total_live} kênh livestream (phân nhóm theo giải)")
    print(f"   • Thời gian: {elapsed:.1f}s")

if __name__ == "__main__":
    main()
