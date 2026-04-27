import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import json
import re
import gzip
import io
from collections import defaultdict

# ================================================
# SCRIPT LẤY LỊCH TRẬN BÓNG ĐÁ & TENNIS (5 NGUỒN)
# ✅ StarHub: Premier League, FA Cup, Tennis
# ✅ nt74: Tennis
# ✅ xvb: Tennis
# ✅ PT1 (Bồ Đào Nha): Bóng đá nam + Tennis
# ✅ RO1 (Romania): Bóng đá nam + Tennis
# ✅ Sửa lỗi trùng tên đội, mở rộng viết tắt, loại bỏ chương trình phi trận đấu
# ✅ Chỉ lấy trận từ -6h đến +72h
# ================================================

EPG_URL_STARHUB = "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml"
EPG_URL_NT74 = "https://raw.githubusercontent.com/nt74/epglist/refs/heads/main/guide.xml"
EPG_URL_XVB = "https://raw.githubusercontent.com/xvb-lab/xvb-epg/refs/heads/main/epg/epg-fr.xml"
EPG_URL_PT1 = "https://epgshare01.online/epgshare01/epg_ripper_PT1.xml.gz"
EPG_URL_RO1 = "https://epgshare01.online/epgshare01/epg_ripper_RO1.xml.gz"
OUTPUT_FILE = "live_matches.json"
HOURS_BEFORE = 6
HOURS_AFTER = 72

# ==================== DANH SÁCH GIẢI ĐẤU & ĐỘI BÓNG ====================
ALLOWED_LEAGUES = {
    "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "UEFA Euro", "FIFA World Cup", "International Friendlies", "FA Cup", "Carabao Cup"
}

PREMIER_LEAGUE_TEAMS = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham",
    "west ham united", "wolverhampton"
}

ALLOWED_TEAMS_PER_LEAGUE = {
    "Premier League": PREMIER_LEAGUE_TEAMS,
    "Serie A": {"inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"},
    "La Liga": {"barcelona", "real madrid", "atletico madrid"},
    "Bundesliga": {"bayern munich", "borussia dortmund", "bayer leverkusen"},
    "Ligue 1": {"paris saint-germain", "marseille", "olympique marseille"},
    "FA Cup": PREMIER_LEAGUE_TEAMS,
    "Carabao Cup": PREMIER_LEAGUE_TEAMS,
}

EUROPEAN_COUNTRIES = {
    "albania", "andorra", "armenia", "austria", "azerbaijan", "belarus", "belgium", "bosnia",
    "bulgaria", "croatia", "cyprus", "czech", "denmark", "england", "estonia", "faroe",
    "finland", "france", "georgia", "germany", "gibraltar", "greece", "hungary", "iceland",
    "israel", "italy", "kazakhstan", "kosovo", "latvia", "liechtenstein", "lithuania",
    "luxembourg", "malta", "moldova", "monaco", "montenegro", "netherlands", "north macedonia",
    "northern ireland", "norway", "poland", "portugal", "republic of ireland", "romania",
    "russia", "san marino", "scotland", "serbia", "slovakia", "slovenia", "spain", "sweden",
    "switzerland", "turkey", "ukraine", "wales"
}

AMERICAS_TEAMS = {"argentina", "brazil"}
ASIA_TEAMS = {"japan", "south korea"}

# ==================== TỪ KHÓA LOẠI TRỪ ====================
WOMEN_KEYWORDS = [
    "women", "womens", "women's", "woman", "female",
    "frauen", "damen", "weiblich",
    "donne", "femminile",
    "mujeres", "femenino", "femenina",
    "femmes", "féminin", "féminine",
    "mulheres", "feminino",
    "vrouwen", "női", "kadın",
]

YOUTH_KEYWORDS = [
    "youth", "junior", "academy", "reserves", "reserve", "ii", "b",
    "zweite", "second team", "sub", "u-", "under",
    "jugend", "juniorer",
    "giovanili", "primavera",
    "cantera", "filial",
    "jeunes", "espoirs",
    "jong", "beloften",
]

NON_MATCH_KEYWORDS = [
    "estúdios", "estúdio", "antevisão", "antevisao", "magazine", "debate",
    "pré-jogo", "pos-jogo", "pre-jogo", "pos-jogo", "highlight", "highlights",
    "resumo", "compacto", "análise", "analise", "comentário", "comentario",
    "review", "preview", "previa", "previo", "flash", "interview", "entrevista",
    "conference", "press", "conferência", "conferencia",
]

# ==================== MAP CHUẨN HÓA TÊN ĐỘI (MỞ RỘNG) ====================
TEAM_NORMALIZE_MAP = {
    # Premier League
    "man. united": "manchester united",
    "man united": "manchester united",
    "man utd": "manchester united",
    "man. city": "manchester city",
    "man city": "manchester city",
    "wolves": "wolverhampton",
    "spurs": "tottenham",
    "newcastle": "newcastle",
    "brighton": "brighton",
    "brentford": "brentford",
    # Serie A
    "inter": "inter milan",
    "milan": "ac milan",
    "juve": "juventus",
    "napoli": "napoli",
    "roma": "roma",
    "atalanta": "atalanta",
    "lazio": "lazio",
    # La Liga
    "barcelona": "barcelona",
    "barça": "barcelona",
    "barca": "barcelona",
    "real madrid": "real madrid",
    "real": "real madrid",
    "atlético": "atletico madrid",
    "atletico": "atletico madrid",
    # Bundesliga
    "bayern": "bayern munich",
    "b. munique": "bayern munich",
    "b. münchen": "bayern munich",
    "b. munich": "bayern munich",
    "bayern münchen": "bayern munich",
    "borussia dortmund": "borussia dortmund",
    "dortmund": "borussia dortmund",
    "b. dortmund": "borussia dortmund",
    "bayer leverkusen": "bayer leverkusen",
    "leverkusen": "bayer leverkusen",
    "b. leverkusen": "bayer leverkusen",
    # Ligue 1
    "psg": "paris saint-germain",
    "paris sg": "paris saint-germain",
    "marseille": "olympique marseille",
    "om": "olympique marseille",
    "olympique marseille": "olympique marseille",
}

# ==================== TIỆN ÍCH CHUNG ====================
def download_xml(url: str) -> str:
    print(f"📥 Đang tải EPG từ {url.split('/')[-1]}...")
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    print(f"✅ Tải thành công ({len(response.content):,} bytes)")
    return response.text

def download_and_decompress_gz(url: str) -> str:
    print(f"📥 Đang tải & giải nén EPG từ {url.split('/')[-1]}...")
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    buf = io.BytesIO(response.content)
    with gzip.GzipFile(fileobj=buf) as f:
        xml_bytes = f.read()
    print(f"✅ Giải nén thành công ({len(xml_bytes):,} bytes)")
    return xml_bytes.decode('utf-8')

def has_live_indicator_starhub(title: str, desc: str) -> bool:
    text = f"{title} {desc}".lower()
    return bool(re.search(r'\(live\)', text, re.IGNORECASE))

def has_live_indicator_fr(desc: str) -> bool:
    return bool(re.search(r'en\s+direct', desc, re.IGNORECASE))

def is_live_pt1(title: str) -> bool:
    return "(Direto)" in title

def is_live_ro1(title: str) -> bool:
    return bool(re.search(r'\bLive\b', title))

def is_women_or_youth(title: str) -> bool:
    lower = title.lower()
    for kw in WOMEN_KEYWORDS:
        if kw in lower:
            return True
    for kw in YOUTH_KEYWORDS:
        if kw in lower:
            return True
    return False

def is_tennis_title(title: str) -> bool:
    text = title.lower()
    tennis_keywords = {
        "atp", "wta", "tenis", "tennis", "atp tour", "wta tour", "grand slam",
        "australian open", "roland garros", "french open", "wimbledon", "us open",
        "madrid open", "mutua madrid", "davis cup", "laver cup"
    }
    has_tennis = any(kw in text for kw in tennis_keywords)
    has_padel = "padel" in text or "padbol" in text
    return has_tennis and not has_padel

def parse_tennis_matchup(title: str) -> tuple[str, str]:
    clean_title = re.sub(r'\(Live\)', '', title, flags=re.IGNORECASE).strip()
    clean_title = re.sub(r'\(Direto\)', '', clean_title, flags=re.IGNORECASE).strip()
    clean_title = re.sub(r'^(Tennis|Tenis)\s*:\s*', '', clean_title, flags=re.IGNORECASE).strip()
    clean_title = re.sub(r'^Live\s+', '', clean_title, flags=re.IGNORECASE).strip()
    if ":" in clean_title:
        parts = clean_title.split(":", 1)
        league_candidate = parts[0].strip()
        matchup_candidate = parts[1].strip()
        if any(kw in league_candidate.lower() for kw in ["atp", "wta", "tournoi", "tennis", "tenis"]):
            return league_candidate, matchup_candidate
    text = clean_title.lower()
    if "atp masters" in text:
        league = "ATP Masters"
    elif "wta 1000" in text:
        league = "WTA 1000"
    elif "tournoi wta" in text or "wta" in text:
        league = "WTA"
    elif "atp" in text:
        league = "ATP"
    else:
        league = "Tennis"
    return league, clean_title

# ==================== XỬ LÝ GIẢI ĐẤU & ĐỘI BÓNG ====================
def extract_league_from_title(title: str):
    lower = title.lower()
    league_patterns = [
        (r'uefa\s+europa\s+conference\s+league', 'UEFA Europa Conference League'),
        (r'uefa\s+europa\s+league', 'UEFA Europa League'),
        (r'uefa\s+champions\s+league', 'UEFA Champions League'),
        (r'premier\s+league', 'Premier League'),
        (r'serie\s+a\b', 'Serie A'),
        (r'la\s+liga', 'La Liga'),
        (r'bundesliga', 'Bundesliga'),
        (r'ligue\s+1', 'Ligue 1'),
        (r'fa\s+cup', 'FA Cup'),
        (r'carabao\s+cup', 'Carabao Cup'),
        (r'uefa\s+euro', 'UEFA Euro'),
        (r'fifa\s+world\s+cup', 'FIFA World Cup'),
        (r'international\s+friendlies', 'International Friendlies'),
    ]
    for pattern, league_name in league_patterns:
        if re.search(pattern, lower):
            return league_name, title
    return None, title

def is_valid_match(title: str, league: str) -> bool:
    if is_women_or_youth(title):
        return False
    if league in ["UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League", "FIFA World Cup"]:
        return True
    if league == "UEFA Euro":
        lower = title.lower()
        return any(country in lower for country in EUROPEAN_COUNTRIES)
    if league == "International Friendlies":
        allowed = EUROPEAN_COUNTRIES | AMERICAS_TEAMS | ASIA_TEAMS
        lower = title.lower()
        found = [c for c in allowed if c in lower]
        return len(found) >= 2
    teams = find_allowed_teams_in_text(title, league)
    return len(teams) > 0

def find_allowed_teams_in_text(text: str, league: str) -> list:
    if league not in ALLOWED_TEAMS_PER_LEAGUE or ALLOWED_TEAMS_PER_LEAGUE[league] is None:
        return []
    allowed_teams = ALLOWED_TEAMS_PER_LEAGUE[league]
    lower_text = text.lower()
    # Áp dụng chuẩn hóa
    for abbr, full in TEAM_NORMALIZE_MAP.items():
        lower_text = re.sub(r'\b' + re.escape(abbr) + r'\b', full, lower_text)
    found = []
    for team in allowed_teams:
        if team in lower_text:
            found.append(team)
    return found

def clean_football_matchup_generic(title: str, league: str):
    """Trả về matchup string hoặc None nếu không phải trận đấu thực sự."""
    lower_title = title.lower()
    for kw in NON_MATCH_KEYWORDS:
        if kw in lower_title:
            return None

    cleaned = re.sub(r'\(Direto\)', '', title, flags=re.IGNORECASE)
    cleaned = re.sub(r'\(Live\)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bLive\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bMd\d+\b', '', cleaned)
    cleaned = re.sub(r'\bJornada\s+\d+\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\d{4}-\d{2}', '', cleaned)
    # Loại bỏ tên giải đấu
    for pattern, lname in [
        (r'premier\s+league', 'Premier League'),
        (r'serie\s+a\b', 'Serie A'),
        (r'la\s+liga', 'La Liga'),
        (r'bundesliga', 'Bundesliga'),
        (r'ligue\s+1', 'Ligue 1'),
        (r'fa\s+cup', 'FA Cup'),
        (r'carabao\s+cup', 'Carabao Cup'),
        (r'uefa\s+champions\s+league', 'UEFA Champions League'),
        (r'uefa\s+europa\s+league', 'UEFA Europa League'),
    ]:
        if league == lname:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip('- ')
    # Tìm cặp đấu
    match = re.search(r'\s+vs\s+', cleaned)
    if not match:
        match = re.search(r'\s+x\s+', cleaned)
    if not match:
        match = re.search(r'\s+v\s+', cleaned)
    if not match:
        return None
    parts = [p.strip() for p in re.split(r'\s+(?:vs|x|v)\s+', cleaned, maxsplit=1)]
    if len(parts) != 2:
        return None
    team1_raw, team2_raw = parts
    team1_raw = re.sub(r'\s*-.*$', '', team1_raw).strip()
    team2_raw = re.sub(r'\s*-.*$', '', team2_raw).strip()
    if not team1_raw or not team2_raw:
        return None
    for kw in NON_MATCH_KEYWORDS:
        if kw in team1_raw.lower() or kw in team2_raw.lower():
            return None

    def norm(name):
        n = name.lower()
        for abbr, full in TEAM_NORMALIZE_MAP.items():
            n = re.sub(r'\b' + re.escape(abbr) + r'\b', full, n)
        return n

    tn1 = norm(team1_raw)
    tn2 = norm(team2_raw)
    if league in ALLOWED_TEAMS_PER_LEAGUE and ALLOWED_TEAMS_PER_LEAGUE[league]:
        allowed = ALLOWED_TEAMS_PER_LEAGUE[league]
        t1f = next((t for t in allowed if t in tn1), tn1.title())
        t2f = next((t for t in allowed if t in tn2), tn2.title())
    else:
        t1f = tn1.title()
        t2f = tn2.title()
    return f"{t1f} vs {t2f}"

# ==================== ĐỊNH DẠNG TÊN KÊNH ====================
def format_channel_starhub(name: str) -> str:
    if re.search(r'bein\s*sports', name, re.IGNORECASE):
        return f"{name} Malaysia"
    return name

def format_channel_nt74(channel_id: str) -> str:
    match = re.match(r'sportklub(\d+)\.rs', channel_id, re.IGNORECASE)
    if match:
        return f"Sport Klub {match.group(1)} Hrvatska"
    return channel_id.replace('.rs', '').upper()

def format_channel_xvb(channel_id: str) -> str:
    name = re.sub(r'\.fr$', '', channel_id, flags=re.IGNORECASE)
    name = name.replace('.', ' ')
    name = name.title()
    name = re.sub(r'\bBein\b', 'beIN', name)
    return f"{name} France"

def format_channel_pt1(channel_id: str) -> str:
    name = channel_id.replace('.pt', '').replace('.', ' ')
    name = name.title()
    return f"{name} Portugal"

def format_channel_ro1(channel_id: str) -> str:
    name = channel_id.replace('.ro', '').replace('.', ' ')
    name = name.title()
    return f"{name} Romania"

# ==================== PARSE CÁC NGUỒN ====================
def parse_start_time(start_str: str) -> datetime:
    try:
        return datetime.strptime(start_str, "%Y%m%d%H%M%S %z")
    except ValueError:
        dt_naive = datetime.strptime(start_str[:14], "%Y%m%d%H%M%S")
        return dt_naive.replace(tzinfo=timezone.utc)

def is_within_time_window(start_utc: datetime, now_utc: datetime) -> bool:
    return (now_utc - timedelta(hours=HOURS_BEFORE)) <= start_utc <= (now_utc + timedelta(hours=HOURS_AFTER))

def _groups_to_output(groups: dict) -> list:
    output = []
    for (date, time, _), items in groups.items():
        first = items[0]
        services = sorted({item["channel"] for item in items})
        output.append({
            "Date": date,
            "Time": time,
            "League": first["league"],
            "Matchup": first["matchup"],
            "Services": services
        })
    output.sort(key=lambda x: (x["Date"], x["Time"]))
    return output

def merge_match_lists(*lists) -> list:
    merged = defaultdict(list)
    for lst in lists:
        for item in lst:
            key = (item["Date"], item["Time"], item["Matchup"].lower())
            merged[key].append(item)
    final_output = []
    for (date, time, _), items in merged.items():
        league = next((it["League"] for it in items if it["League"]), "Unknown")
        all_services = set()
        for it in items:
            all_services.update(it["Services"])
        final_output.append({
            "Date": date,
            "Time": time,
            "League": league,
            "Matchup": items[0]["Matchup"],
            "Services": sorted(all_services)
        })
    final_output.sort(key=lambda x: (x["Date"], x["Time"]))
    return final_output

# --- StarHub ---
def parse_channels_starhub(xml_content: str) -> dict:
    root = ET.fromstring(xml_content)
    channels = {}
    for channel in root.findall("channel"):
        chan_id = channel.get("id")
        display_name = channel.findtext("display-name", "").strip()
        if chan_id and display_name:
            channels[chan_id] = display_name
    print(f"📺 Tìm thấy {len(channels)} kênh (StarHub)")
    return channels

def is_fa_cup(title: str) -> bool:
    return bool(re.search(r'\bFA\s+Cup\b', title, re.IGNORECASE))

def extract_teams_starhub(text: str) -> list:
    lower_text = text.lower()
    for abbr, full in TEAM_ABBR_STARHUB.items():
        lower_text = lower_text.replace(abbr, full)
    found = []
    for team in sorted(PREMIER_LEAGUE_TEAMS, key=len, reverse=True):
        if team in lower_text:
            if not any(team != existing and team in existing for existing in found):
                found.append(team)
    return found

def has_any_premier_league_team(text: str) -> bool:
    return len(extract_teams_starhub(text)) > 0

def is_premier_league(title: str, desc: str) -> bool:
    if not has_live_indicator_starhub(title, desc):
        return False
    if is_fa_cup(title):
        return False
    teams = extract_teams_starhub(title + " " + desc)
    return len(teams) >= 2

def clean_football_matchup_starhub(title: str) -> str:
    title = re.sub(r'\(Live\)', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\(MW\d+\)', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\(Goal\s*Rush\)', '', title, flags=re.IGNORECASE)
    title = re.sub(r'-\s*EP\s*\d+', '', title, flags=re.IGNORECASE)
    title = re.sub(r'LFCTV[^:]*:', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s+v\s+', ' vs ', title)
    title = re.sub(r'\s+', ' ', title).strip()
    teams = extract_teams_starhub(title)
    if len(teams) >= 2:
        lower_title = title.lower()
        positions = [(team, lower_title.find(team)) for team in teams if team in lower_title]
        positions.sort(key=lambda x: x[1])
        team1 = positions[0][0].title()
        team2 = positions[1][0].title()
        return f"{team1} vs {team2}"
    elif len(teams) == 1:
        parts = [p.strip() for p in title.split(' vs ', 1)]
        if len(parts) == 2:
            return f"{parts[0]} vs {parts[1]}"
        return title
    else:
        return title

TEAM_ABBR_STARHUB = {
    "rpool": "liverpool",
    "man city": "manchester city",
    "man utd": "manchester united",
    "newcastle": "newcastle",
    "wolves": "wolverhampton",
    "fulham": "fulham",
    "everton": "everton",
}

def parse_programmes_starhub(xml_content: str, channels: dict) -> list:
    root = ET.fromstring(xml_content)
    groups = defaultdict(list)
    now_utc = datetime.now(timezone.utc)
    for prog in root.findall("programme"):
        channel_id = prog.get("channel")
        start_str = prog.get("start")
        title_elem = prog.find("title")
        desc_elem = prog.find("desc")
        if title_elem is None or not start_str:
            continue
        title = (title_elem.text or "").strip()
        desc = (desc_elem.text or "").strip() if desc_elem is not None else ""
        league = None
        matchup = None
        if is_fa_cup(title) and has_live_indicator_starhub(title, desc):
            if has_any_premier_league_team(title + " " + desc):
                league = "FA Cup"
                matchup = clean_football_matchup_starhub(title)
        elif is_premier_league(title, desc):
            league = "Premier League"
            matchup = clean_football_matchup_starhub(title)
        elif is_tennis_title(title) and has_live_indicator_starhub(title, desc):
            league, matchup = parse_tennis_matchup(title)
        else:
            continue
        dt_utc = parse_start_time(start_str)
        if not is_within_time_window(dt_utc, now_utc):
            continue
        dt_vn = dt_utc + timedelta(hours=7)
        date_str = dt_vn.strftime("%Y-%m-%d")
        time_str = dt_vn.strftime("%H:%M")
        raw_name = channels.get(channel_id, f"Channel {channel_id}")
        channel_name = format_channel_starhub(raw_name)
        key = (date_str, time_str, matchup.lower())
        groups[key].append({
            "channel": channel_name,
            "league": league,
            "matchup": matchup,
            "date": date_str,
            "time": time_str,
        })
    return _groups_to_output(groups)

# --- nt74 ---
def parse_programmes_nt74(xml_content: str) -> list:
    root = ET.fromstring(xml_content)
    groups = defaultdict(list)
    now_utc = datetime.now(timezone.utc)
    for prog in root.findall("programme"):
        channel_id = prog.get("channel")
        start_str = prog.get("start")
        title_elem = prog.find("title")
        desc_elem = prog.find("desc")
        if title_elem is None or not start_str:
            continue
        title = (title_elem.text or "").strip()
        desc = (desc_elem.text or "").strip() if desc_elem is not None else ""
        if not (is_tennis_title(title) and has_live_indicator_starhub(title, desc)):
            continue
        league, matchup = parse_tennis_matchup(title)
        dt_utc = parse_start_time(start_str)
        if not is_within_time_window(dt_utc, now_utc):
            continue
        dt_vn = dt_utc + timedelta(hours=7)
        date_str = dt_vn.strftime("%Y-%m-%d")
        time_str = dt_vn.strftime("%H:%M")
        channel_name = format_channel_nt74(channel_id) if channel_id else "Unknown"
        key = (date_str, time_str, matchup.lower())
        groups[key].append({
            "channel": channel_name,
            "league": league,
            "matchup": matchup,
            "date": date_str,
            "time": time_str,
        })
    return _groups_to_output(groups)

# --- xvb ---
def parse_programmes_xvb(xml_content: str) -> list:
    root = ET.fromstring(xml_content)
    groups = defaultdict(list)
    now_utc = datetime.now(timezone.utc)
    for prog in root.findall("programme"):
        channel_id = prog.get("channel")
        start_str = prog.get("start")
        title_elem = prog.find("title")
        desc_elem = prog.find("desc")
        if title_elem is None or not start_str:
            continue
        title = (title_elem.text or "").strip()
        desc = (desc_elem.text or "").strip() if desc_elem is not None else ""
        if not is_tennis_title(title) or not has_live_indicator_fr(desc):
            continue
        league, matchup = parse_tennis_matchup(title)
        dt_utc = parse_start_time(start_str)
        if not is_within_time_window(dt_utc, now_utc):
            continue
        dt_vn = dt_utc + timedelta(hours=7)
        date_str = dt_vn.strftime("%Y-%m-%d")
        time_str = dt_vn.strftime("%H:%M")
        channel_name = format_channel_xvb(channel_id) if channel_id else "Unknown"
        key = (date_str, time_str, matchup.lower())
        groups[key].append({
            "channel": channel_name,
            "league": league,
            "matchup": matchup,
            "date": date_str,
            "time": time_str,
        })
    return _groups_to_output(groups)

# --- PT1 & RO1 ---
def parse_programmes_epgshare(xml_content: str, source: str) -> list:
    root = ET.fromstring(xml_content)
    groups = defaultdict(list)
    now_utc = datetime.now(timezone.utc)
    is_pt = (source == 'PT1')
    for prog in root.findall("programme"):
        channel_id = prog.get("channel")
        start_str = prog.get("start")
        title_elem = prog.find("title")
        desc_elem = prog.find("desc")
        if title_elem is None or not start_str:
            continue
        title = (title_elem.text or "").strip()
        desc = (desc_elem.text or "").strip() if desc_elem is not None else ""
        if is_pt and not is_live_pt1(title):
            continue
        if not is_pt and not is_live_ro1(title):
            continue
        league, _ = extract_league_from_title(title)
        if league and league in ALLOWED_LEAGUES:
            if not is_valid_match(title, league):
                continue
            matchup = clean_football_matchup_generic(title, league)
            if matchup is None:
                continue
        elif is_tennis_title(title):
            league, matchup = parse_tennis_matchup(title)
            if not league:
                continue
        else:
            continue
        dt_utc = parse_start_time(start_str)
        if not is_within_time_window(dt_utc, now_utc):
            continue
        dt_vn = dt_utc + timedelta(hours=7)
        date_str = dt_vn.strftime("%Y-%m-%d")
        time_str = dt_vn.strftime("%H:%M")
        if is_pt:
            channel_name = format_channel_pt1(channel_id)
        else:
            channel_name = format_channel_ro1(channel_id)
        key = (date_str, time_str, matchup.lower())
        groups[key].append({
            "channel": channel_name,
            "league": league,
            "matchup": matchup,
            "date": date_str,
            "time": time_str,
        })
    return _groups_to_output(groups)

# ==================== MAIN ====================
def main():
    try:
        # StarHub
        xml_starhub = download_xml(EPG_URL_STARHUB)
        ch_starhub = parse_channels_starhub(xml_starhub)
        matches_starhub = parse_programmes_starhub(xml_starhub, ch_starhub)
        print(f"⚽🎾 StarHub: {len(matches_starhub)} trận")

        # nt74
        xml_nt74 = download_xml(EPG_URL_NT74)
        matches_nt74 = parse_programmes_nt74(xml_nt74)
        print(f"🎾 nt74: {len(matches_nt74)} trận")

        # xvb
        xml_xvb = download_xml(EPG_URL_XVB)
        matches_xvb = parse_programmes_xvb(xml_xvb)
        print(f"🎾 xvb (France): {len(matches_xvb)} trận")

        # PT1
        xml_pt1 = download_and_decompress_gz(EPG_URL_PT1)
        matches_pt1 = parse_programmes_epgshare(xml_pt1, 'PT1')
        print(f"🇵🇹 PT1: {len(matches_pt1)} trận")

        # RO1
        xml_ro1 = download_and_decompress_gz(EPG_URL_RO1)
        matches_ro1 = parse_programmes_epgshare(xml_ro1, 'RO1')
        print(f"🇷🇴 RO1: {len(matches_ro1)} trận")

        all_matches = merge_match_lists(matches_starhub, matches_nt74, matches_xvb, matches_pt1, matches_ro1)
        print(f"📋 Tổng sau gộp: {len(all_matches)} trận")

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_matches, f, ensure_ascii=False, indent=2)

        print(f"✅ Hoàn thành! Đã lưu {OUTPUT_FILE}")

    except Exception as e:
        print(f"❌ Lỗi: {e}")
        raise

if __name__ == "__main__":
    main()
