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
# ✅ Gộp kênh theo thời gian lệch ≤ 30 phút
# ✅ Trích xuất đội bóng bằng danh sách thông minh
# ✅ Hỗ trợ đầy đủ viết tắt đội bóng (Man. United, PSG, B. Munique...)
# ================================================

EPG_URL_STARHUB = "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml"
EPG_URL_NT74 = "https://raw.githubusercontent.com/nt74/epglist/refs/heads/main/guide.xml"
EPG_URL_XVB = "https://raw.githubusercontent.com/xvb-lab/xvb-epg/refs/heads/main/epg/epg-fr.xml"
EPG_URL_PT1 = "https://epgshare01.online/epgshare01/epg_ripper_PT1.xml.gz"
EPG_URL_RO1 = "https://epgshare01.online/epgshare01/epg_ripper_RO1.xml.gz"
OUTPUT_FILE = "live_matches.json"
HOURS_BEFORE = 6
HOURS_AFTER = 72
MERGE_TIME_TOLERANCE_MINUTES = 30   # gộp nếu cùng ngày, lệch giờ ≤ 30 phút

# ==================== DANH SÁCH GIẢI ĐẤU VÀ ĐỘI BÓNG ====================
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

# Tập hợp tất cả các tên đội (đã chuẩn hóa) từ các giải – dùng cho Champions League, v.v.
ALL_KNOWN_TEAMS = set().union(*[teams for league, teams in ALLOWED_TEAMS_PER_LEAGUE.items() if teams is not None])

EUROPEAN_COUNTRIES = {
    "albania", "andorra", "armenia", "austria", "azerbaijan", "belarus", "belgium", "bosnia",
    "bulgaria", "croatia", "cyprus", "czech", "denmark", "england", "estonia", "faroe",
    "finland", "france", "georgia", "germany", "gibraltar", "greece", "hungary", "iceland",
    "israel", "italy", "kazakhstan", "kosovo", "latvia", "liechtenstein", "lithuania",
    "luxembourg", "malta", "moldova", "monaco", "montenegro", "netherlands", "macedonia",
    "northern ireland", "norway", "poland", "portugal", "republic of ireland", "romania",
    "russia", "san marino", "scotland", "serbia", "slovakia", "slovenia", "spain", "sweden",
    "switzerland", "turkey", "ukraine", "wales"
}
AMERICAS_TEAMS = {"argentina", "brazil"}
ASIA_TEAMS = {"japan", "south korea"}

# Từ khóa loại trừ (giải nữ, trẻ, chương trình không phải trận đấu)
WOMEN_KEYWORDS = [
    "women", "womens", "women's", "woman", "female",
    "frauen", "damen", "weiblich", "donne", "femminile",
    "mujeres", "femenino", "femenina", "femmes", "féminin", "féminine",
    "mulheres", "feminino", "vrouwen", "női", "kadın"
]
YOUTH_KEYWORDS = [
    "youth", "junior", "academy", "reserves", "reserve", "ii", "b",
    "zweite", "second team", "sub", "u-", "under",
    "jugend", "juniorer", "giovanili", "primavera", "cantera", "filial",
    "jeunes", "espoirs", "jong", "beloften"
]
NON_MATCH_KEYWORDS = [
    "estúdios", "estúdio", "antevisão", "antevisao", "magazine", "debate",
    "pré-jogo", "pos-jogo", "highlight", "resumo", "compacto", "análise",
    "comentário", "review", "preview", "flash", "interview", "entrevista",
    "conference", "press"
]

# ==================== CHUẨN HÓA TÊN ĐỘI (MỞ RỘNG) ====================
TEAM_NORMALIZE_MAP = {
    # Premier League
    "man. united": "manchester united", "man united": "manchester united",
    "man utd": "manchester united", "man. city": "manchester city",
    "man city": "manchester city", "wolves": "wolverhampton",
    "spurs": "tottenham", "newcastle": "newcastle",
    "brighton": "brighton", "brentford": "brentford",
    # Serie A
    "inter": "inter milan", "milan": "ac milan", "juve": "juventus",
    "napoli": "napoli", "roma": "roma", "atalanta": "atalanta", "lazio": "lazio",
    # La Liga
    "barcelona": "barcelona", "barça": "barcelona", "barca": "barcelona",
    "real madrid": "real madrid", "real": "real madrid",
    "atlético": "atletico madrid", "atletico": "atletico madrid",
    # Bundesliga
    "bayern": "bayern munich", "b. munique": "bayern munich",
    "b. münchen": "bayern munich", "b. munich": "bayern munich",
    "borussia dortmund": "borussia dortmund", "dortmund": "borussia dortmund",
    "b. dortmund": "borussia dortmund",
    "bayer leverkusen": "bayer leverkusen", "leverkusen": "bayer leverkusen",
    "b. leverkusen": "bayer leverkusen",
    # Ligue 1
    "psg": "paris saint-germain", "paris sg": "paris saint-germain",
    "marseille": "olympique marseille", "om": "olympique marseille",
}

# ==================== TIỆN ÍCH CHUNG ====================
def download_xml(url: str) -> str:
    print(f"📥 Đang tải EPG từ {url.split('/')[-1]}...")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    print(f"✅ Tải thành công ({len(resp.content):,} bytes)")
    return resp.text

def download_and_decompress_gz(url: str) -> str:
    print(f"📥 Đang tải & giải nén {url.split('/')[-1]}...")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with gzip.GzipFile(fileobj=io.BytesIO(resp.content)) as f:
        data = f.read()
    print(f"✅ Giải nén thành công ({len(data):,} bytes)")
    return data.decode('utf-8')

def has_live_indicator_starhub(title: str, desc: str) -> bool:
    return bool(re.search(r'\(live\)', f"{title} {desc}", re.IGNORECASE))

def has_live_indicator_fr(desc: str) -> bool:
    return bool(re.search(r'en\s+direct', desc, re.IGNORECASE))

def is_live_pt1(title: str) -> bool:
    return "(Direto)" in title

def is_live_ro1(title: str) -> bool:
    return bool(re.search(r'\bLive\b', title))

def is_women_or_youth(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in WOMEN_KEYWORDS) or any(kw in t for kw in YOUTH_KEYWORDS)

def is_tennis_title(title: str) -> bool:
    t = title.lower()
    kw = {"atp", "wta", "tenis", "tennis", "grand slam", "australian open", "roland garros",
          "french open", "wimbledon", "us open", "madrid open", "mutua madrid", "davis cup", "laver cup"}
    return any(w in t for w in kw) and not any(p in t for p in ["padel", "padbol"])

def parse_tennis_matchup(title: str) -> tuple[str, str]:
    clean = re.sub(r'\((?:Live|Direto)\)', '', title, flags=re.IGNORECASE).strip()
    clean = re.sub(r'^(Tennis|Tenis)\s*:\s*', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'^Live\s+', '', clean, flags=re.IGNORECASE)
    if ":" in clean:
        left, right = clean.split(":", 1)
        if any(k in left.lower() for k in ["atp", "wta", "tournoi", "tennis"]):
            return left.strip(), right.strip()
    l = clean.lower()
    if "atp masters" in l: league = "ATP Masters"
    elif "wta 1000" in l: league = "WTA 1000"
    elif "tournoi wta" in l or "wta" in l: league = "WTA"
    elif "atp" in l: league = "ATP"
    else: league = "Tennis"
    return league, clean

# ==================== XỬ LÝ GIẢI ĐẤU & ĐỘI BÓNG ====================
def extract_league_from_title(title: str):
    t = title.lower()
    patterns = [
        (r'uefa\s+europa\s+conference\s+league', 'UEFA Europa Conference League'),
        (r'uefa\s+europa\s+league', 'UEFA Europa League'),
        (r'uefa\s+champions\s+league', 'UEFA Champions League'),
        (r'premier\s+league', 'Premier League'),
        (r'serie\s+a\b', 'Serie A'), (r'la\s+liga', 'La Liga'),
        (r'bundesliga', 'Bundesliga'), (r'ligue\s+1', 'Ligue 1'),
        (r'fa\s+cup', 'FA Cup'), (r'carabao\s+cup', 'Carabao Cup'),
        (r'uefa\s+euro', 'UEFA Euro'), (r'fifa\s+world\s+cup', 'FIFA World Cup'),
        (r'international\s+friendlies', 'International Friendlies')
    ]
    for pat, name in patterns:
        if re.search(pat, t):
            return name, title
    return None, title

def is_valid_match(title: str, league: str) -> bool:
    if is_women_or_youth(title):
        return False
    if league in {"UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League", "FIFA World Cup"}:
        return True
    if league == "UEFA Euro":
        return any(c in title.lower() for c in EUROPEAN_COUNTRIES)
    if league == "International Friendlies":
        allowed = EUROPEAN_COUNTRIES | AMERICAS_TEAMS | ASIA_TEAMS
        found = [c for c in allowed if c in title.lower()]
        return len(found) >= 2
    # Các giải có danh sách đội
    teams = find_allowed_teams_in_text(title, league)
    return len(teams) > 0

def find_allowed_teams_in_text(text: str, league: str) -> list:
    if league not in ALLOWED_TEAMS_PER_LEAGUE or ALLOWED_TEAMS_PER_LEAGUE[league] is None:
        return []
    allowed = ALLOWED_TEAMS_PER_LEAGUE[league]
    txt = text.lower()
    for abbr, full in TEAM_NORMALIZE_MAP.items():
        txt = re.sub(r'\b' + re.escape(abbr) + r'\b', full, txt)
    return [team for team in allowed if team in txt]

# ==================== TRÍCH XUẤT MATCHUP THÔNG MINH ====================
def clean_football_matchup_generic(title: str, league: str) -> str or None:
    """Tìm 2 đội bóng đã biết trong title, trả về 'Team1 vs Team2' hoặc None."""
    # Loại bỏ tag
    clean = re.sub(r'\((?:Direto|Live)\)', '', title, flags=re.IGNORECASE)
    clean = re.sub(r'\bLive\b', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\b(Md|Jornada)\s*\d+\b', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\d{4}-\d{2}', '', clean)
    # Chuẩn hóa khoảng trắng
    clean = re.sub(r'\s+', ' ', clean).strip()

    # Chuẩn hóa toàn bộ văn bản (tên viết tắt)
    norm = clean.lower()
    for abbr, full in TEAM_NORMALIZE_MAP.items():
        norm = re.sub(r'\b' + re.escape(abbr) + r'\b', full, norm)

    # Các đội đã biết (từ tất cả giải) để tìm
    known_teams = ALL_KNOWN_TEAMS   # tập các tên đã chuẩn hóa (vd: "manchester united", "brentford")
    found = []
    for team in known_teams:
        if team in norm:
            start = norm.index(team)
            found.append((start, team))
    if len(found) < 2:
        return None
    found.sort(key=lambda x: x[0])
    t1 = found[0][1]
    t2 = found[1][1]
    # Trả về với viết hoa đẹp: dùng tên từ tập gốc (đã có sẵn)
    # Tuy nhiên tên trong known_teams đã là chữ thường, ta có thể viết hoa từng chữ cái đầu
    def pretty(name):
        return name.title()
    return f"{pretty(t1)} vs {pretty(t2)}"

# ==================== ĐỊNH DẠNG TÊN KÊNH ====================
def format_channel_starhub(name: str) -> str:
    return f"{name} Malaysia" if re.search(r'bein\s*sports', name, re.IGNORECASE) else name

def format_channel_nt74(channel_id: str) -> str:
    m = re.match(r'sportklub(\d+)\.rs', channel_id, re.IGNORECASE)
    return f"Sport Klub {m.group(1)} Hrvatska" if m else channel_id.replace('.rs', '').upper()

def format_channel_xvb(channel_id: str) -> str:
    name = re.sub(r'\.fr$', '', channel_id, flags=re.IGNORECASE).replace('.', ' ')
    name = name.title()
    name = re.sub(r'\bBein\b', 'beIN', name)
    return f"{name} France"

def format_channel_pt1(channel_id: str) -> str:
    name = channel_id.replace('.pt', '').replace('.', ' ').title()
    return f"{name} Portugal"

def format_channel_ro1(channel_id: str) -> str:
    name = channel_id.replace('.ro', '').replace('.', ' ').title()
    return f"{name} Romania"

# ==================== XỬ LÝ THỜI GIAN ====================
def parse_start_time(start_str: str) -> datetime:
    try:
        return datetime.strptime(start_str, "%Y%m%d%H%M%S %z")
    except ValueError:
        return datetime.strptime(start_str[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)

def is_within_time_window(start_utc: datetime, now_utc: datetime) -> bool:
    return now_utc - timedelta(hours=HOURS_BEFORE) <= start_utc <= now_utc + timedelta(hours=HOURS_AFTER)

# ==================== PARSE CÁC NGUỒN ====================
def parse_programmes_starhub(xml_content: str, channels: dict) -> list:
    root = ET.fromstring(xml_content)
    groups = defaultdict(list)
    now = datetime.now(timezone.utc)
    for prog in root.findall("programme"):
        cid = prog.get("channel")
        start = prog.get("start")
        tel = prog.find("title")
        if tel is None or not start: continue
        title = (tel.text or "").strip()
        desc = (prog.find("desc").text or "").strip() if prog.find("desc") is not None else ""
        league = matchup = None
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
        dt_utc = parse_start_time(start)
        if not is_within_time_window(dt_utc, now): continue
        dt_vn = dt_utc + timedelta(hours=7)
        ch_name = format_channel_starhub(channels.get(cid, f"Channel {cid}"))
        groups[(dt_vn, matchup.lower())].append({
            "channel": ch_name, "league": league, "matchup": matchup,
            "start_utc": dt_utc
        })
    return _groups_to_output(groups)

def parse_programmes_nt74(xml_content: str) -> list:
    root = ET.fromstring(xml_content)
    groups = defaultdict(list)
    now = datetime.now(timezone.utc)
    for prog in root.findall("programme"):
        cid = prog.get("channel")
        start = prog.get("start")
        tel = prog.find("title")
        if tel is None or not start: continue
        title = (tel.text or "").strip()
        desc = (prog.find("desc").text or "").strip() if prog.find("desc") is not None else ""
        if not (is_tennis_title(title) and has_live_indicator_starhub(title, desc)): continue
        league, matchup = parse_tennis_matchup(title)
        dt_utc = parse_start_time(start)
        if not is_within_time_window(dt_utc, now): continue
        dt_vn = dt_utc + timedelta(hours=7)
        ch_name = format_channel_nt74(cid) if cid else "Unknown"
        groups[(dt_vn, matchup.lower())].append({
            "channel": ch_name, "league": league, "matchup": matchup,
            "start_utc": dt_utc
        })
    return _groups_to_output(groups)

def parse_programmes_xvb(xml_content: str) -> list:
    root = ET.fromstring(xml_content)
    groups = defaultdict(list)
    now = datetime.now(timezone.utc)
    for prog in root.findall("programme"):
        cid = prog.get("channel")
        start = prog.get("start")
        tel = prog.find("title")
        if tel is None or not start: continue
        title = (tel.text or "").strip()
        desc = (prog.find("desc").text or "").strip() if prog.find("desc") is not None else ""
        if not is_tennis_title(title) or not has_live_indicator_fr(desc): continue
        league, matchup = parse_tennis_matchup(title)
        dt_utc = parse_start_time(start)
        if not is_within_time_window(dt_utc, now): continue
        dt_vn = dt_utc + timedelta(hours=7)
        ch_name = format_channel_xvb(cid) if cid else "Unknown"
        groups[(dt_vn, matchup.lower())].append({
            "channel": ch_name, "league": league, "matchup": matchup,
            "start_utc": dt_utc
        })
    return _groups_to_output(groups)

def parse_programmes_epgshare(xml_content: str, source: str) -> list:
    root = ET.fromstring(xml_content)
    groups = defaultdict(list)
    now = datetime.now(timezone.utc)
    is_pt = source == 'PT1'
    for prog in root.findall("programme"):
        cid = prog.get("channel")
        start = prog.get("start")
        tel = prog.find("title")
        if tel is None or not start: continue
        title = (tel.text or "").strip()
        if is_pt and not is_live_pt1(title): continue
        if not is_pt and not is_live_ro1(title): continue
        league, _ = extract_league_from_title(title)
        if league and league in ALLOWED_LEAGUES:
            if not is_valid_match(title, league): continue
            matchup = clean_football_matchup_generic(title, league)
            if matchup is None: continue
        elif is_tennis_title(title):
            league, matchup = parse_tennis_matchup(title)
            if not league: continue
        else:
            continue
        dt_utc = parse_start_time(start)
        if not is_within_time_window(dt_utc, now): continue
        dt_vn = dt_utc + timedelta(hours=7)
        ch_name = format_channel_pt1(cid) if is_pt else format_channel_ro1(cid)
        groups[(dt_vn, matchup.lower())].append({
            "channel": ch_name, "league": league, "matchup": matchup,
            "start_utc": dt_utc
        })
    return _groups_to_output(groups)

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
    """
    Gộp các trận cùng ngày, chênh lệch giờ ≤ MERGE_TIME_TOLERANCE_MINUTES,
    lấy giờ sớm nhất làm giờ hiển thị.
    """
    # Gom tất cả items vào dict key = (date, matchup_lower)
    from collections import defaultdict
    raw = defaultdict(list)
    for lst in lists:
        for item in lst:
            key = (item["Date"], item["Matchup"].lower())
            raw[key].append(item)
    final = []
    for (date, _), items in raw.items():
        # Nhóm theo khung giờ: chuyển Time thành số phút từ 0h
        def time_to_min(t):
            h, m = map(int, t.split(":"))
            return h * 60 + m
        # Sắp xếp theo phút
        items_sorted = sorted(items, key=lambda x: time_to_min(x["Time"]))
        # Gom thành cluster cách nhau ≤ MERGE_TIME_TOLERANCE_MINUTES
        clusters = []
        cur_cluster = []
        last_min = -9999
        for it in items_sorted:
            t_min = time_to_min(it["Time"])
            if cur_cluster and (t_min - last_min > MERGE_TIME_TOLERANCE_MINUTES):
                clusters.append(cur_cluster)
                cur_cluster = []
            cur_cluster.append(it)
            last_min = t_min
        if cur_cluster:
            clusters.append(cur_cluster)
        for cluster in clusters:
            # Lấy giờ sớm nhất
            earliest = min(cluster, key=lambda x: time_to_min(x["Time"]))
            # Gom tất cả kênh
            services = sorted({ch for it in cluster for ch in it["Services"]})
            league = cluster[0]["League"]  # giả định cùng league
            final.append({
                "Date": date,
                "Time": earliest["Time"],
                "League": league,
                "Matchup": earliest["Matchup"],
                "Services": services
            })
    final.sort(key=lambda x: (x["Date"], x["Time"]))
    return final

# ==================== CÁC HÀM PHỤ CHO STARHUB ====================
def is_fa_cup(title: str) -> bool:
    return bool(re.search(r'\bFA\s+Cup\b', title, re.IGNORECASE))

def has_any_premier_league_team(text: str) -> bool:
    t = text.lower()
    for abbr, full in TEAM_ABBR_STARHUB.items():
        t = t.replace(abbr, full)
    return any(team in t for team in PREMIER_LEAGUE_TEAMS)

def extract_teams_starhub(text: str) -> list:
    t = text.lower()
    for abbr, full in TEAM_ABBR_STARHUB.items():
        t = t.replace(abbr, full)
    found = []
    for team in sorted(PREMIER_LEAGUE_TEAMS, key=len, reverse=True):
        if team in t and not any(team != ex and team in ex for ex in found):
            found.append(team)
    return found

def is_premier_league(title: str, desc: str) -> bool:
    if not has_live_indicator_starhub(title, desc) or is_fa_cup(title):
        return False
    return len(extract_teams_starhub(title + " " + desc)) >= 2

def clean_football_matchup_starhub(title: str) -> str:
    t = re.sub(r'\(Live\)', '', title, flags=re.IGNORECASE)
    t = re.sub(r'\(MW\d+\)', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\(Goal\s*Rush\)', '', t, flags=re.IGNORECASE)
    t = re.sub(r'-\s*EP\s*\d+', '', t, flags=re.IGNORECASE)
    t = re.sub(r'LFCTV[^:]*:', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+v\s+', ' vs ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    teams = extract_teams_starhub(t)
    if len(teams) >= 2:
        pos = [(team, t.lower().find(team)) for team in teams if team in t.lower()]
        pos.sort(key=lambda x: x[1])
        return f"{pos[0][0].title()} vs {pos[1][0].title()}"
    elif len(teams) == 1:
        parts = [p.strip() for p in t.split(' vs ', 1)]
        return f"{parts[0]} vs {parts[1]}" if len(parts) == 2 else t
    return t

TEAM_ABBR_STARHUB = {
    "rpool": "liverpool", "man city": "manchester city", "man utd": "manchester united",
    "newcastle": "newcastle", "wolves": "wolverhampton", "fulham": "fulham", "everton": "everton",
}

def parse_channels_starhub(xml_content: str) -> dict:
    root = ET.fromstring(xml_content)
    return {c.get("id"): c.findtext("display-name", "").strip()
            for c in root.findall("channel") if c.get("id") and c.findtext("display-name")}

# ==================== MAIN ====================
def main():
    try:
        # StarHub
        xml_s = download_xml(EPG_URL_STARHUB)
        ch_s = parse_channels_starhub(xml_s)
        m_s = parse_programmes_starhub(xml_s, ch_s)
        print(f"⚽🎾 StarHub: {len(m_s)} trận")

        # nt74
        m_n = parse_programmes_nt74(download_xml(EPG_URL_NT74))
        print(f"🎾 nt74: {len(m_n)} trận")

        # xvb
        m_x = parse_programmes_xvb(download_xml(EPG_URL_XVB))
        print(f"🎾 xvb (France): {len(m_x)} trận")

        # PT1
        m_pt = parse_programmes_epgshare(download_and_decompress_gz(EPG_URL_PT1), 'PT1')
        print(f"🇵🇹 PT1: {len(m_pt)} trận")

        # RO1
        m_ro = parse_programmes_epgshare(download_and_decompress_gz(EPG_URL_RO1), 'RO1')
        print(f"🇷🇴 RO1: {len(m_ro)} trận")

        all_m = merge_match_lists(m_s, m_n, m_x, m_pt, m_ro)
        print(f"📋 Tổng sau gộp: {len(all_m)} trận")

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_m, f, ensure_ascii=False, indent=2)
        print(f"✅ Hoàn thành! Đã lưu {OUTPUT_FILE}")

    except Exception as e:
        print(f"❌ Lỗi: {e}")
        raise

if __name__ == "__main__":
    main()
