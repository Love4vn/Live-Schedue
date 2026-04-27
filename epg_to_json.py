import requests
import re
import gzip
import io
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# ================================================
# LIVE MATCHES EPG - ĐÃ SỬA LỖI (?i) FLAG
# Hoạt động tốt với nguồn PT1 (Bồ Đào Nha)
# ================================================

EPG_URL_PT1 = "https://epgshare01.online/epgshare01/epg_ripper_PT1.xml.gz"
EPG_URL_RO1 = "https://epgshare01.online/epgshare01/epg_ripper_RO1.xml.gz"

OUTPUT_FILE = "live_matches.json"

HOURS_BEFORE = 6
HOURS_AFTER = 72
MERGE_TIME_TOLERANCE_MINUTES = 30

ALLOWED_LEAGUES = {
    "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "FA Cup", "Carabao Cup"
}

PREMIER_LEAGUE_TEAMS = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "tottenham",
    "west ham united", "wolverhampton"
}

ALLOWED_TEAMS_PER_LEAGUE = {
    "Premier League": PREMIER_LEAGUE_TEAMS,
    "Serie A": {"inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"},
    "La Liga": {"barcelona", "real madrid", "atletico madrid"},
    "Bundesliga": {"bayern munich", "borussia dortmund", "bayer leverkusen"},
    "Ligue 1": {"paris saint-germain", "olympique marseille"},
    "FA Cup": PREMIER_LEAGUE_TEAMS,
    "Carabao Cup": PREMIER_LEAGUE_TEAMS,
}

ALL_KNOWN_TEAMS = set().union(*[teams for teams in ALLOWED_TEAMS_PER_LEAGUE.values() if teams])

TEAM_NORMALIZE_MAP = {
    "man. united": "manchester united", "man united": "manchester united", "man utd": "manchester united",
    "man. city": "manchester city", "man city": "manchester city",
    "wolves": "wolverhampton", "spurs": "tottenham",
    "inter": "inter milan", "milan": "ac milan", "juve": "juventus",
    "barça": "barcelona", "barca": "barcelona", "real": "real madrid",
    "atlético": "atletico madrid", "atletico": "atletico madrid",
    "bayern": "bayern munich", "b. munique": "bayern munich", "b. munich": "bayern munich",
    "b. dortmund": "borussia dortmund", "dortmund": "borussia dortmund",
    "leverkusen": "bayer leverkusen",
    "psg": "paris saint-germain", "paris sg": "paris saint-germain",
    "marseille": "olympique marseille", "om": "olympique marseille",
}

WOMEN_KEYWORDS = ["women", "womens", "frauen", "féminine"]
YOUTH_KEYWORDS = ["youth", "junior", "u-", "under", "reserves", "academy"]

# ==================== TIỆN ÍCH ====================
def download_and_decompress_gz(url: str) -> str:
    print(f"📥 Đang tải & giải nén {url.split('/')[-1]}...")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with gzip.GzipFile(fileobj=io.BytesIO(resp.content)) as f:
        data = f.read()
    print(f"✅ Giải nén thành công ({len(data):,} bytes)")
    return data.decode('utf-8')

# ==================== LÀM SẠCH TIÊU ĐỀ PT1 (ĐÃ SỬA FLAG (?i)) ====================
def clean_portuguese_football_title(title: str) -> str:
    t = title.strip()
    
    # Sử dụng re.IGNORECASE thay vì (?i) ở giữa pattern
    t = re.sub(r'^\d+\s+', '', t, flags=re.IGNORECASE)                    # bỏ số kênh
    t = re.sub(r'^assista ao jogo da\s+', '', t, flags=re.IGNORECASE)     # bỏ "Assista ao jogo da"
    t = re.sub(r'\.\s*futebol\s*$', '', t, flags=re.IGNORECASE)           # bỏ ". Futebol"
    t = re.sub(r'\s+futebol\s*$', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+->\s+', ' vs ', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+[xX]\s+', ' vs ', t, flags=re.IGNORECASE)             # Man United x Brentford
    t = re.sub(r'\s+versus\s+', ' vs ', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+', ' ', t).strip()
    
    return t

def extract_league_and_matchup_pt(title: str) -> tuple[str | None, str | None]:
    cleaned = clean_portuguese_football_title(title)
    if not cleaned:
        return None, None

    # Tìm league
    league, _ = extract_league_from_title(cleaned)
    if not league:
        pt_patterns = {
            r'premier league': 'Premier League',
            r'serie a': 'Serie A',
            r'la liga': 'La Liga',
            r'bundesliga': 'Bundesliga',
            r'ligue 1': 'Ligue 1',
            r'champions league': 'UEFA Champions League',
            r'europa league': 'UEFA Europa League',
        }
        t_lower = cleaned.lower()
        for pat, name in pt_patterns.items():
            if re.search(pat, t_lower):
                league = name
                break

    if not league:
        return None, None

    matchup = clean_football_matchup_generic(cleaned, league)
    if not matchup and ' vs ' in cleaned:
        parts = [p.strip().title() for p in cleaned.split(' vs ', 1)]
        if len(parts) == 2:
            matchup = f"{parts[0]} vs {parts[1]}"

    return league, matchup

def extract_league_from_title(title: str):
    t = title.lower()
    patterns = [
        (r'uefa champions league', 'UEFA Champions League'),
        (r'uefa europa league', 'UEFA Europa League'),
        (r'uefa europa conference', 'UEFA Europa Conference League'),
        (r'premier league', 'Premier League'),
        (r'serie a', 'Serie A'),
        (r'la liga', 'La Liga'),
        (r'bundesliga', 'Bundesliga'),
        (r'ligue 1', 'Ligue 1'),
        (r'fa cup', 'FA Cup'),
        (r'carabao cup', 'Carabao Cup'),
    ]
    for pat, name in patterns:
        if re.search(pat, t):
            return name, title
    return None, title

def clean_football_matchup_generic(title: str, league: str) -> str | None:
    clean = re.sub(r'\((?:Direto|Live)\)', '', title, flags=re.IGNORECASE)
    clean = re.sub(r'\bLive\b', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'^\d+\s+', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()

    norm = clean.lower()
    for abbr, full in TEAM_NORMALIZE_MAP.items():
        norm = re.sub(r'\b' + re.escape(abbr) + r'\b', full, norm)

    found = []
    for team in sorted(ALL_KNOWN_TEAMS, key=len, reverse=True):
        if team in norm:
            found.append((norm.find(team), team))
            if len(found) >= 2:
                break

    if len(found) >= 2:
        found.sort(key=lambda x: x[0])
        return f"{found[0][1].title()} vs {found[1][1].title()}"

    if ' vs ' in clean:
        parts = [p.strip().title() for p in clean.split(' vs ', 1)]
        if len(parts) == 2:
            return f"{parts[0]} vs {parts[1]}"
    return None

def is_live_pt1(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in ["(direto)", "ao vivo", "assista ao jogo", "futebol", "live"])

def is_live_ro1(title: str) -> bool:
    return bool(re.search(r'\blive\b', title, flags=re.IGNORECASE))

def parse_tennis_matchup(title: str) -> tuple[str, str]:
    clean = re.sub(r'\((?:Live|Direto)\)', '', title, flags=re.IGNORECASE).strip()
    return "Tennis", clean

# ==================== PARSE EPGSHARE ====================
def parse_programmes_epgshare(xml_content: str, source: str) -> list:
    root = ET.fromstring(xml_content)
    groups = defaultdict(list)
    now = datetime.now(timezone.utc)
    is_pt = source == 'PT1'

    for prog in root.findall("programme"):
        cid = prog.get("channel")
        start = prog.get("start")
        tel = prog.find("title")
        if not tel or not start:
            continue

        title = tel.text.strip() if tel.text else ""
        
        if is_pt and not is_live_pt1(title):
            continue
        if not is_pt and not is_live_ro1(title):
            continue

        league = matchup = None
        if is_pt:
            league, matchup = extract_league_and_matchup_pt(title)
        else:
            league, _ = extract_league_from_title(title)
            if league:
                matchup = clean_football_matchup_generic(title, league)

        if not league or not matchup:
            continue

        try:
            dt_utc = datetime.strptime(start[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except:
            continue

        if not (now - timedelta(hours=HOURS_BEFORE) <= dt_utc <= now + timedelta(hours=HOURS_AFTER)):
            continue

        dt_vn = dt_utc + timedelta(hours=7)
        ch_name = f"{cid.replace('.pt','').replace('.',' ').title()} Portugal" if is_pt else \
                  f"{cid.replace('.ro','').replace('.',' ').title()} Romania"

        groups[(dt_vn, matchup.lower())].append({
            "channel": ch_name,
            "league": league,
            "matchup": matchup,
            "start_utc": dt_utc
        })

    # Chuyển thành list output
    output = []
    for (dt_vn, _), items in groups.items():
        date = dt_vn.strftime("%Y-%m-%d")
        time_str = dt_vn.strftime("%H:%M")
        services = sorted({it["channel"] for it in items})
        output.append({
            "Date": date,
            "Time": time_str,
            "League": items[0]["league"],
            "Matchup": items[0]["matchup"],
            "Services": services
        })
    output.sort(key=lambda x: (x["Date"], x["Time"]))
    return output

def merge_match_lists(*lists) -> list:
    from collections import defaultdict
    raw = defaultdict(list)
    for lst in lists:
        for item in lst:
            key = (item["Date"], item["Matchup"].lower())
            raw[key].append(item)

    final = []
    for (date, _), items in raw.items():
        items_sorted = sorted(items, key=lambda x: x["Time"])
        earliest = items_sorted[0]
        services = sorted({ch for it in items_sorted for ch in it["Services"]})
        final.append({
            "Date": date,
            "Time": earliest["Time"],
            "League": earliest["League"],
            "Matchup": earliest["Matchup"],
            "Services": services
        })
    final.sort(key=lambda x: (x["Date"], x["Time"]))
    return final

# ==================== MAIN ====================
def main():
    try:
        print("🚀 Bắt đầu lấy lịch trận từ PT1 và RO1...")

        m_pt = parse_programmes_epgshare(download_and_decompress_gz(EPG_URL_PT1), 'PT1')
        print(f"🇵🇹 PT1: {len(m_pt)} trận")

        m_ro = parse_programmes_epgshare(download_and_decompress_gz(EPG_URL_RO1), 'RO1')
        print(f"🇷🇴 RO1: {len(m_ro)} trận")

        all_matches = merge_match_lists(m_pt, m_ro)

        print(f"📋 Tổng số trận sau gộp: {len(all_matches)}")

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_matches, f, ensure_ascii=False, indent=2)

        print(f"✅ Hoàn thành! File {OUTPUT_FILE} đã được tạo.")

        # In thử 8 trận đầu để kiểm tra
        print("\n📋 Một số trận mẫu:")
        for m in all_matches[:8]:
            print(f"  {m['Date']} {m['Time']} | {m['League']} | {m['Matchup']} | {', '.join(m['Services'])}")

    except Exception as e:
        print(f"❌ Lỗi: {e}")
        raise

if __name__ == "__main__":
    main()
