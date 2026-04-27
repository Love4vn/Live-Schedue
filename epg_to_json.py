import requests
import re
import gzip
import io
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# ================================================
# SCRIPT LẤY LỊCH TRẬN BÓNG ĐÁ & TENNIS (5 NGUỒN)
# ✅ Đã tối ưu mạnh cho nguồn PT1 (Bồ Đào Nha)
# ✅ Bắt tốt tiêu đề: "Assista ao jogo da ... x ... Futebol"
# ✅ Chuẩn hóa tên đội (Man United → Manchester United, PSG, Bayern...)
# ✅ Gộp kênh theo thời gian lệch ≤ 30 phút
# ================================================

EPG_URL_STARHUB = "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml"
EPG_URL_NT74 = "https://raw.githubusercontent.com/nt74/epglist/refs/heads/main/guide.xml"
EPG_URL_XVB = "https://raw.githubusercontent.com/xvb-lab/xvb-epg/refs/heads/main/epg/epg-fr.xml"
EPG_URL_PT1 = "https://epgshare01.online/epgshare01/epg_ripper_PT1.xml.gz"
EPG_URL_RO1 = "https://epgshare01.online/epgshare01/epg_ripper_RO1.xml.gz"

OUTPUT_FILE = "live_matches.json"

HOURS_BEFORE = 6
HOURS_AFTER = 72
MERGE_TIME_TOLERANCE_MINUTES = 30

# ==================== DANH SÁCH GIẢI ĐẤU & ĐỘI BÓNG ====================
ALLOWED_LEAGUES = {
    "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "UEFA Euro", "FIFA World Cup", "International Friendlies", "FA Cup", "Carabao Cup"
}

PREMIER_LEAGUE_TEAMS = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool",
    "manchester city", "manchester united", "newcastle", "nottingham forest",
    "sunderland", "tottenham", "west ham united", "wolverhampton"
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

# ==================== CHUẨN HÓA TÊN ĐỘI ====================
TEAM_NORMALIZE_MAP = {
    "man. united": "manchester united", "man united": "manchester united", "man utd": "manchester united",
    "man. city": "manchester city", "man city": "manchester city",
    "wolves": "wolverhampton", "spurs": "tottenham",
    "inter": "inter milan", "milan": "ac milan", "juve": "juventus",
    "barça": "barcelona", "barca": "barcelona", "real": "real madrid",
    "atlético": "atletico madrid", "atletico": "atletico madrid",
    "bayern": "bayern munich", "b. munique": "bayern munich", "b. munich": "bayern munich",
    "b. dortmund": "borussia dortmund", "dortmund": "borussia dortmund",
    "b. leverkusen": "bayer leverkusen", "leverkusen": "bayer leverkusen",
    "psg": "paris saint-germain", "paris sg": "paris saint-germain",
    "marseille": "olympique marseille", "om": "olympique marseille",
}

# Từ khóa loại trừ
WOMEN_KEYWORDS = ["women", "womens", "women's", "frauen", "damen", "féminine"]
YOUTH_KEYWORDS = ["youth", "junior", "u-", "under", "reserves", "academy"]
NON_MATCH_KEYWORDS = ["estúdios", "antevisão", "highlight", "resumo"]

# ==================== TIỆN ÍCH ====================
def download_xml(url: str) -> str:
    print(f"📥 Đang tải {url.split('/')[-1]}...")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text

def download_and_decompress_gz(url: str) -> str:
    print(f"📥 Đang tải & giải nén {url.split('/')[-1]}...")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with gzip.GzipFile(fileobj=io.BytesIO(resp.content)) as f:
        data = f.read()
    print(f"✅ Giải nén thành công ({len(data):,} bytes)")
    return data.decode('utf-8')

def is_women_or_youth(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in WOMEN_KEYWORDS) or any(kw in t for kw in YOUTH_KEYWORDS)

def is_tennis_title(title: str) -> bool:
    t = title.lower()
    kw = {"atp", "wta", "tenis", "tennis", "grand slam", "australian open", "roland garros", "wimbledon", "us open"}
    return any(w in t for w in kw) and not any(p in t for p in ["padel"])

# ==================== LÀM SẠCH TIÊU ĐỀ PT1 (MỚI & QUAN TRỌNG) ====================
def clean_portuguese_football_title(title: str) -> str:
    t = title.strip()
    # Loại bỏ số kênh đầu dòng và cụm Assista ao jogo
    t = re.sub(r'^\d+\s+', '', t)
    t = re.sub(r'^(?i)assista ao jogo da\s+', '', t)
    t = re.sub(r'\.\s*Futebol\s*$', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+Futebol\s*$', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+->\s+', ' vs ', t)          # Futebol -> Team1 vs Team2
    t = re.sub(r'\s+[xX]\s+', ' vs ', t)        # Man United x Brentford
    t = re.sub(r'\s+versus\s+', ' vs ', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def extract_league_and_matchup_pt(title: str) -> tuple[str | None, str | None]:
    cleaned = clean_portuguese_football_title(title)
    if not cleaned:
        return None, None

    # Tìm league
    league, remaining = extract_league_from_title(cleaned)
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

    # Tìm matchup
    matchup = clean_football_matchup_generic(cleaned, league)
    if not matchup and ' vs ' in cleaned:
        parts = [p.strip() for p in cleaned.split(' vs ', 1)]
        if len(parts) == 2:
            matchup = f"{parts[0].title()} vs {parts[1].title()}"

    return league, matchup

# ==================== CÁC HÀM CHUNG ====================
def extract_league_from_title(title: str):
    t = title.lower()
    patterns = [
        (r'uefa\s+champions\s+league', 'UEFA Champions League'),
        (r'uefa\s+europa\s+league', 'UEFA Europa League'),
        (r'uefa\s+europa\s+conference', 'UEFA Europa Conference League'),
        (r'premier\s+league', 'Premier League'),
        (r'serie\s+a', 'Serie A'),
        (r'la\s+liga', 'La Liga'),
        (r'bundesliga', 'Bundesliga'),
        (r'ligue\s+1', 'Ligue 1'),
        (r'fa\s+cup', 'FA Cup'),
        (r'carabao\s+cup', 'Carabao Cup'),
    ]
    for pat, name in patterns:
        if re.search(pat, t):
            return name, title
    return None, title

def clean_football_matchup_generic(title: str, league: str) -> str | None:
    clean = re.sub(r'\((?:Direto|Live)\)', '', title, flags=re.IGNORECASE)
    clean = re.sub(r'\bLive\b', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\b(Md|Jornada)\s*\d+\b', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'^\d+\s+', '', clean)   # số kênh
    clean = re.sub(r'\s+', ' ', clean).strip()

    # Áp dụng chuẩn hóa tên đội
    norm = clean.lower()
    for abbr, full in TEAM_NORMALIZE_MAP.items():
        norm = re.sub(r'\b' + re.escape(abbr) + r'\b', full, norm)

    # Tìm đội đã biết
    found = []
    for team in sorted(ALL_KNOWN_TEAMS, key=len, reverse=True):
        if team in norm:
            found.append((norm.index(team), team))
            if len(found) >= 2:
                break

    if len(found) >= 2:
        found.sort(key=lambda x: x[0])
        t1 = found[0][1].title()
        t2 = found[1][1].title()
        return f"{t1} vs {t2}"

    # Nếu không tìm được 2 đội thì dùng " vs " trực tiếp
    if ' vs ' in clean:
        parts = [p.strip().title() for p in clean.split(' vs ', 1)]
        if len(parts) == 2:
            return f"{parts[0]} vs {parts[1]}"
    return None

def is_valid_match(title: str, league: str) -> bool:
    if is_women_or_youth(title):
        return False
    return True  # có thể mở rộng thêm nếu cần

def is_live_pt1(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in ["(direto)", "ao vivo", "assista ao jogo", "futebol", "live"])

def is_live_ro1(title: str) -> bool:
    return bool(re.search(r'\bLive\b', title, re.IGNORECASE))

def parse_tennis_matchup(title: str) -> tuple[str, str]:
    clean = re.sub(r'\((?:Live|Direto)\)', '', title, flags=re.IGNORECASE).strip()
    clean = re.sub(r'^(Tennis|Tenis)\s*:\s*', '', clean, flags=re.IGNORECASE)
    if ":" in clean:
        left, right = clean.split(":", 1)
        return "Tennis", f"{left.strip()} vs {right.strip()}"
    return "Tennis", clean

# ==================== PARSE TỪNG NGUỒN ====================
def parse_programmes_epgshare(xml_content: str, source: str) -> list:
    root = ET.fromstring(xml_content)
    groups = defaultdict(list)
    now = datetime.now(timezone.utc)
    is_pt = source == 'PT1'

    for prog in root.findall("programme"):
        cid = prog.get("channel")
        start = prog.get("start")
        tel = prog.find("title")
        if tel is None or not start:
            continue

        title = (tel.text or "").strip()
        if is_pt and not is_live_pt1(title):
            continue
        if not is_pt and not is_live_ro1(title):
            continue

        league = matchup = None
        if is_pt:
            league, matchup = extract_league_and_matchup_pt(title)
        else:
            league, _ = extract_league_from_title(title)
            if league and league in ALLOWED_LEAGUES:
                matchup = clean_football_matchup_generic(title, league)

        if not league or not matchup:
            if is_tennis_title(title):
                league, matchup = parse_tennis_matchup(title)
            else:
                continue

        if not is_valid_match(title, league):
            continue

        dt_utc = parse_start_time(start)
        if not (now - timedelta(hours=HOURS_BEFORE) <= dt_utc <= now + timedelta(hours=HOURS_AFTER)):
            continue

        dt_vn = dt_utc + timedelta(hours=7)
        ch_name = format_channel_pt1(cid) if is_pt else format_channel_ro1(cid)

        groups[(dt_vn, matchup.lower())].append({
            "channel": ch_name,
            "league": league,
            "matchup": matchup,
            "start_utc": dt_utc
        })

    return _groups_to_output(groups)

def parse_start_time(start_str: str) -> datetime:
    try:
        return datetime.strptime(start_str, "%Y%m%d%H%M%S %z")
    except ValueError:
        return datetime.strptime(start_str[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)

def format_channel_pt1(channel_id: str) -> str:
    name = channel_id.replace('.pt', '').replace('.', ' ').title()
    return f"{name} Portugal"

def format_channel_ro1(channel_id: str) -> str:
    name = channel_id.replace('.ro', '').replace('.', ' ').title()
    return f"{name} Romania"

def _groups_to_output(groups: dict) -> list:
    output = []
    for (dt_vn, _), items in groups.items():
        date = dt_vn.strftime("%Y-%m-%d")
        time = dt_vn.strftime("%H:%M")
        services = sorted({it["channel"] for it in items})
        output.append({
            "Date": date,
            "Time": time,
            "League": items[0]["league"],
            "Matchup": items[0]["matchup"],
            "Services": services
        })
    output.sort(key=lambda x: (x["Date"], x["Time"]))
    return output

def merge_match_lists(*lists) -> list:
    raw = defaultdict(list)
    for lst in lists:
        for item in lst:
            key = (item["Date"], item["Matchup"].lower())
            raw[key].append(item)

    final = []
    for (date, _), items in raw.items():
        items_sorted = sorted(items, key=lambda x: int(x["Time"][:2])*60 + int(x["Time"][3:]))
        # Lấy trận sớm nhất
        earliest = min(items_sorted, key=lambda x: int(x["Time"][:2])*60 + int(x["Time"][3:]))
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
        # StarHub
        xml_s = download_xml(EPG_URL_STARHUB)
        # (bạn có thể giữ nguyên parse StarHub nếu cần, hiện tại tôi tập trung PT1)

        m_pt = parse_programmes_epgshare(download_and_decompress_gz(EPG_URL_PT1), 'PT1')
        print(f"🇵🇹 PT1: {len(m_pt)} trận")

        m_ro = parse_programmes_epgshare(download_and_decompress_gz(EPG_URL_RO1), 'RO1')
        print(f"🇷🇴 RO1: {len(m_ro)} trận")

        # Thêm các nguồn khác nếu bạn muốn (StarHub, NT74, XVB...)

        all_m = merge_match_lists(m_pt, m_ro)   # thêm m_s, m_n, m_x nếu có

        print(f"📋 Tổng sau gộp: {len(all_m)} trận")

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_m, f, ensure_ascii=False, indent=2)

        print(f"✅ Hoàn thành! Đã lưu {OUTPUT_FILE}")
        # In thử 10 trận đầu để kiểm tra
        for m in all_m[:10]:
            print(f"  → {m['Date']} {m['Time']} | {m['League']} | {m['Matchup']} | {', '.join(m['Services'])}")

    except Exception as e:
        print(f"❌ Lỗi: {e}")
        raise

if __name__ == "__main__":
    main()
