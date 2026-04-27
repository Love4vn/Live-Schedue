import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import json
import re
import gzip
import io
from collections import defaultdict

# ================================================
# SCRIPT LẤY LỊCH TRẬN BÓNG ĐÁ & TENNIS (5 NGUỒN) – FINAL
# ================================================

EPG_URL_STARHUB = "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml"
EPG_URL_NT74 = "https://raw.githubusercontent.com/nt74/epglist/refs/heads/main/guide.xml"
EPG_URL_XVB = "https://raw.githubusercontent.com/xvb-lab/xvb-epg/refs/heads/main/epg/epg-fr.xml"
EPG_URL_PT1 = "https://epgshare01.online/epgshare01/epg_ripper_PT1.xml.gz"
EPG_URL_RO1 = "https://epgshare01.online/epgshare01/epg_ripper_RO1.xml.gz"
OUTPUT_FILE = "live_matches.json"
HOURS_BEFORE = 6
HOURS_AFTER = 72
MERGE_MINUTES = 30

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

# Tập tất cả các tên đội bất kỳ giải nào (dùng cho Champions League, v.v)
ALL_KNOWN_TEAMS = set()
for t in ALLOWED_TEAMS_PER_LEAGUE.values():
    if t is not None:
        ALL_KNOWN_TEAMS.update(t)

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

WOMEN_KEYWORDS = [
    "women", "womens", "women's", "woman", "female", "frauen", "damen", "weiblich",
    "donne", "femminile", "mujeres", "femenino", "femenina", "femmes", "féminin",
    "féminine", "mulheres", "feminino", "vrouwen", "női", "kadın"
]
YOUTH_KEYWORDS = [
    "youth", "junior", "academy", "reserves", "reserve", "ii", "b",
    "zweite", "second team", "sub", "u-", "under", "jugend", "juniorer",
    "giovanili", "primavera", "cantera", "filial", "jeunes", "espoirs",
    "jong", "beloften"
]
NON_MATCH_KEYWORDS = [
    "estúdios", "estúdio", "antevisão", "antevisao", "magazine", "debate",
    "pré-jogo", "pos-jogo", "highlight", "resumo", "compacto", "análise",
    "comentário", "review", "preview", "flash", "interview", "entrevista",
    "conference", "press"
]

# ==================== CHUẨN HÓA TÊN ĐỘI MỞ RỘNG ====================
TEAM_NORMALIZE_MAP = {
    "man. united": "manchester united", "man united": "manchester united",
    "man utd": "manchester united", "man. city": "manchester city",
    "man city": "manchester city", "wolves": "wolverhampton",
    "spurs": "tottenham", "newcastle": "newcastle", "brighton": "brighton",
    "brentford": "brentford",
    "inter": "inter milan", "milan": "ac milan", "juve": "juventus",
    "napoli": "napoli", "roma": "roma", "atalanta": "atalanta", "lazio": "lazio",
    "barcelona": "barcelona", "barça": "barcelona", "barca": "barcelona",
    "real madrid": "real madrid", "real": "real madrid",
    "atlético": "atletico madrid", "atletico": "atletico madrid",
    "bayern": "bayern munich", "b. munique": "bayern munich",
    "b. münchen": "bayern munich", "b. munich": "bayern munich",
    "borussia dortmund": "borussia dortmund", "dortmund": "borussia dortmund",
    "b. dortmund": "borussia dortmund",
    "bayer leverkusen": "bayer leverkusen", "leverkusen": "bayer leverkusen",
    "b. leverkusen": "bayer leverkusen",
    "psg": "paris saint-germain", "paris sg": "paris saint-germain",
    "marseille": "olympique marseille", "om": "olympique marseille",
}

# ==================== TIỆN ÍCH CHUNG ====================
def download(url):
    print(f"📥 {url.split('/')[-1]} ...")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    print(f"✅ {len(r.content):,} bytes")
    return r.text

def download_gz(url):
    print(f"📥 {url.split('/')[-1]} (gzip) ...")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    buf = io.BytesIO(r.content)
    with gzip.GzipFile(fileobj=buf) as f:
        data = f.read()
    print(f"✅ {len(data):,} bytes")
    return data.decode('utf-8')

def has_live_starhub(title, desc):
    return bool(re.search(r'\(live\)', f"{title} {desc}", re.I))

def has_live_fr(desc):
    return bool(re.search(r'en\s+direct', desc, re.I))

def is_live_pt1(title):
    return "(Direto)" in title

def is_live_ro1(title):
    return bool(re.search(r'\bLive\b', title))

def is_women_or_youth(title):
    t = title.lower()
    return any(k in t for k in WOMEN_KEYWORDS) or any(k in t for k in YOUTH_KEYWORDS)

def is_tennis(title):
    t = title.lower()
    return any(w in t for w in ["atp","wta","tenis","tennis","grand slam","australian open","french open","wimbledon","us open"]) and not any(p in t for p in ["padel","padbol"])

def parse_tennis(title):
    c = re.sub(r'\((?:Live|Direto)\)', '', title, flags=re.I).strip()
    c = re.sub(r'^(Tennis|Tenis)\s*:\s*', '', c, flags=re.I)
    c = re.sub(r'^Live\s+', '', c, flags=re.I)
    if ":" in c:
        l, r = c.split(":",1)
        if any(w in l.lower() for w in ["atp","wta","tournoi","tennis"]):
            return l.strip(), r.strip()
    low = c.lower()
    if "atp masters" in low: lg = "ATP Masters"
    elif "wta 1000" in low: lg = "WTA 1000"
    elif "tournoi wta" in low or "wta" in low: lg = "WTA"
    elif "atp" in low: lg = "ATP"
    else: lg = "Tennis"
    return lg, c

# ==================== TRÍCH XUẤT GIẢI ĐẤU ====================
def get_league(title):
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
    for p, name in patterns:
        if re.search(p, t):
            return name, title
    return None, title

def is_valid_match(title, league):
    if is_women_or_youth(title):
        return False
    if league in {"UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League", "FIFA World Cup"}:
        return True
    if league == "UEFA Euro":
        return any(c in title.lower() for c in EUROPEAN_COUNTRIES)
    if league == "International Friendlies":
        allowed = EUROPEAN_COUNTRIES | AMERICAS_TEAMS | ASIA_TEAMS
        return len([c for c in allowed if c in title.lower()]) >= 2
    teams = find_allowed_teams(title, league)
    return len(teams) > 0

def find_allowed_teams(text, league):
    if league not in ALLOWED_TEAMS_PER_LEAGUE or ALLOWED_TEAMS_PER_LEAGUE[league] is None:
        return []
    allowed = ALLOWED_TEAMS_PER_LEAGUE[league]
    norm = text.lower()
    for abbr, full in TEAM_NORMALIZE_MAP.items():
        norm = re.sub(r'\b' + re.escape(abbr) + r'\b', full, norm)
    return [t for t in allowed if t in norm]

# ==================== TRÍCH XUẤT CẶP ĐẤU THÔNG MINH ====================
def clean_matchup(title, league):
    # Loại bỏ các thành phần không cần thiết
    c = re.sub(r'\((?:Direto|Live)\)', '', title, flags=re.I)
    c = re.sub(r'\bLive\b', '', c, flags=re.I)
    c = re.sub(r'\b(Md|Jornada)\s*\d+\b', '', c, flags=re.I)
    c = re.sub(r'\d{4}-\d{2}', '', c)
    # Xóa mô tả vòng đấu thường gặp
    c = re.sub(r'\b\d+ª\s*Mão\s*(da\s*)?(Meia-?Final)?\b', '', c, flags=re.I)
    c = re.sub(r'[-–:]+\s*$', '', c)  # dấu gạch cuối
    c = re.sub(r'\s+', ' ', c).strip()

    norm = c.lower()
    for abbr, full in TEAM_NORMALIZE_MAP.items():
        norm = re.sub(r'\b' + re.escape(abbr) + r'\b', full, norm)

    found = []
    for team in ALL_KNOWN_TEAMS:
        if team in norm:
            idx = norm.index(team)
            found.append((idx, team))
    if len(found) >= 2:
        found.sort(key=lambda x: x[0])
        t1 = found[0][1]
        t2 = found[1][1]
        return f"{t1.title()} vs {t2.title()}"

    # Fallback: thử tách theo dấu 'x', 'vs', 'v'
    sep = None
    for s in [' vs ', ' x ', ' v ']:
        if s in c.lower():
            sep = s
            break
    if sep:
        parts = c.lower().split(sep)
        if len(parts) == 2:
            p1 = normalize_team(parts[0].strip())
            p2 = normalize_team(parts[1].strip())
            # Kiểm tra xem có phải đội đã biết không
            if p1 in ALL_KNOWN_TEAMS or p2 in ALL_KNOWN_TEAMS:
                return f"{p1.title()} vs {p2.title()}"
    return None

def normalize_team(name):
    n = name.lower()
    for abbr, full in TEAM_NORMALIZE_MAP.items():
        n = re.sub(r'\b' + re.escape(abbr) + r'\b', full, n)
    return n

# ==================== ĐỊNH DẠNG KÊNH ====================
def fmt_starhub(name):
    return f"{name} Malaysia" if re.search(r'bein\s*sports', name, re.I) else name

def fmt_nt74(cid):
    m = re.match(r'sportklub(\d+)\.rs', cid, re.I)
    return f"Sport Klub {m.group(1)} Hrvatska" if m else cid.replace('.rs','').upper()

def fmt_xvb(cid):
    n = re.sub(r'\.fr$', '', cid, flags=re.I).replace('.',' ')
    n = n.title()
    n = re.sub(r'\bBein\b', 'beIN', n)
    return f"{n} France"

def fmt_pt1(cid):
    n = cid.replace('.pt','').replace('.',' ').title()
    return f"{n} Portugal"

def fmt_ro1(cid):
    n = cid.replace('.ro','').replace('.',' ').title()
    return f"{n} Romania"

# ==================== PARSE TỪNG NGUỒN ====================
def parse_time(s):
    try:
        return datetime.strptime(s, "%Y%m%d%H%M%S %z")
    except:
        return datetime.strptime(s[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)

def in_window(dt, now):
    return now - timedelta(hours=HOURS_BEFORE) <= dt <= now + timedelta(hours=HOURS_AFTER)

def output(groups):
    out = []
    for (dt_vn, _), items in groups.items():
        d = dt_vn.strftime("%Y-%m-%d")
        t = dt_vn.strftime("%H:%M")
        out.append({
            "Date": d, "Time": t, "League": items[0]["league"],
            "Matchup": items[0]["matchup"], "Services": sorted({it["channel"] for it in items})
        })
    out.sort(key=lambda x: (x["Date"], x["Time"]))
    return out

# StarHub parser
def parse_starhub(xml, ch):
    root = ET.fromstring(xml)
    groups = defaultdict(list)
    now = datetime.now(timezone.utc)
    for p in root.findall("programme"):
        cid = p.get("channel")
        start = p.get("start")
        tel = p.find("title")
        if tel is None or not start: continue
        title = (tel.text or "").strip()
        des = (p.find("desc").text or "").strip() if p.find("desc") is not None else ""
        lg = mt = None
        if is_fa_cup(title) and has_live_starhub(title, des) and has_any_pl_team(title +" "+ des):
            lg = "FA Cup"
            mt = clean_football_starhub(title)
        elif is_pl(title, des):
            lg = "Premier League"
            mt = clean_football_starhub(title)
        elif is_tennis(title) and has_live_starhub(title, des):
            lg, mt = parse_tennis(title)
        else:
            continue
        dt = parse_time(start)
        if not in_window(dt, now): continue
        dt_vn = dt + timedelta(hours=7)
        cn = fmt_starhub(ch.get(cid, f"Ch {cid}"))
        groups[(dt_vn, mt.lower())].append({"channel": cn, "league": lg, "matchup": mt})
    return output(groups)

def is_fa_cup(t):
    return bool(re.search(r'\bFA\s+Cup\b', t, re.I))

def has_any_pl_team(txt):
    return len(extract_teams_starhub(txt)) > 0

def extract_teams_starhub(txt):
    t = txt.lower()
    for a,f in TEAM_ABBR_STARHUB.items(): t = t.replace(a, f)
    teams = []
    for tm in sorted(PREMIER_LEAGUE_TEAMS, key=len, reverse=True):
        if tm in t and not any(tm != ex and tm in ex for ex in teams):
            teams.append(tm)
    return teams

def is_pl(t,d):
    return has_live_starhub(t,d) and not is_fa_cup(t) and len(extract_teams_starhub(t+" "+d)) >= 2

def clean_football_starhub(t):
    t = re.sub(r'\(Live\)', '', t, flags=re.I)
    t = re.sub(r'\(MW\d+\)', '', t, flags=re.I)
    t = re.sub(r'\(Goal\s*Rush\)', '', t, flags=re.I)
    t = re.sub(r'-\s*EP\s*\d+', '', t, flags=re.I)
    t = re.sub(r'LFCTV[^:]*:', '', t, flags=re.I)
    t = re.sub(r'\s+v\s+', ' vs ', t).strip()
    t = re.sub(r'\s+', ' ', t)
    teams = extract_teams_starhub(t)
    if len(teams) >= 2:
        pos = [(tm, t.lower().find(tm)) for tm in teams if tm in t.lower()]
        pos.sort(key=lambda x: x[1])
        return f"{pos[0][0].title()} vs {pos[1][0].title()}"
    elif len(teams) == 1:
        parts = [p.strip() for p in t.split(' vs ')]
        return f"{parts[0]} vs {parts[1]}" if len(parts)==2 else t
    return t

TEAM_ABBR_STARHUB = {
    "rpool":"liverpool","man city":"manchester city","man utd":"manchester united",
    "newcastle":"newcastle","wolves":"wolverhampton","fulham":"fulham","everton":"everton"
}

def parse_channels_starhub(xml):
    root = ET.fromstring(xml)
    return {c.get("id"): c.findtext("display-name","").strip() for c in root.findall("channel") if c.get("id")}

# nt74
def parse_nt74(xml):
    root = ET.fromstring(xml)
    groups = defaultdict(list)
    now = datetime.now(timezone.utc)
    for p in root.findall("programme"):
        cid = p.get("channel")
        start = p.get("start")
        tel = p.find("title")
        if tel is None or not start: continue
        title = (tel.text or "").strip()
        des = (p.find("desc").text or "").strip() if p.find("desc") is not None else ""
        if not (is_tennis(title) and has_live_starhub(title, des)): continue
        lg, mt = parse_tennis(title)
        dt = parse_time(start)
        if not in_window(dt, now): continue
        dt_vn = dt + timedelta(hours=7)
        cn = fmt_nt74(cid) if cid else "Unknown"
        groups[(dt_vn, mt.lower())].append({"channel": cn, "league": lg, "matchup": mt})
    return output(groups)

# xvb
def parse_xvb(xml):
    root = ET.fromstring(xml)
    groups = defaultdict(list)
    now = datetime.now(timezone.utc)
    for p in root.findall("programme"):
        cid = p.get("channel")
        start = p.get("start")
        tel = p.find("title")
        if tel is None or not start: continue
        title = (tel.text or "").strip()
        des = (p.find("desc").text or "").strip() if p.find("desc") is not None else ""
        if not is_tennis(title) or not has_live_fr(des): continue
        lg, mt = parse_tennis(title)
        dt = parse_time(start)
        if not in_window(dt, now): continue
        dt_vn = dt + timedelta(hours=7)
        cn = fmt_xvb(cid) if cid else "Unknown"
        groups[(dt_vn, mt.lower())].append({"channel": cn, "league": lg, "matchup": mt})
    return output(groups)

# PT1 / RO1
def parse_epgshare(xml, src):
    root = ET.fromstring(xml)
    groups = defaultdict(list)
    now = datetime.now(timezone.utc)
    is_pt = src == 'PT1'
    for p in root.findall("programme"):
        cid = p.get("channel")
        start = p.get("start")
        tel = p.find("title")
        if tel is None or not start: continue
        title = (tel.text or "").strip()
        if is_pt and not is_live_pt1(title): continue
        if not is_pt and not is_live_ro1(title): continue
        lg, _ = get_league(title)
        if lg and lg in ALLOWED_LEAGUES:
            if not is_valid_match(title, lg): continue
            mt = clean_matchup(title, lg)
            if mt is None: continue
        elif is_tennis(title):
            lg, mt = parse_tennis(title)
            if not lg: continue
        else:
            continue
        dt = parse_time(start)
        if not in_window(dt, now): continue
        dt_vn = dt + timedelta(hours=7)
        cn = fmt_pt1(cid) if is_pt else fmt_ro1(cid)
        groups[(dt_vn, mt.lower())].append({"channel": cn, "league": lg, "matchup": mt})
    return output(groups)

# ==================== GỘP KÊNH THEO THỜI GIAN ====================
def merge_all(*match_lists):
    from collections import defaultdict
    merged = defaultdict(list)
    for lst in match_lists:
        for it in lst:
            key = (it["Date"], it["Matchup"].lower())
            merged[key].append(it)
    result = []
    for (date, _), items in merged.items():
        # Chuyển Time thành phút
        items = sorted(items, key=lambda x: int(x["Time"][:2])*60 + int(x["Time"][3:]))
        clusters = []
        cur = []
        last_min = -9999
        for it in items:
            m = int(it["Time"][:2])*60 + int(it["Time"][3:])
            if cur and (m - last_min > MERGE_MINUTES):
                clusters.append(cur)
                cur = []
            cur.append(it)
            last_min = m
        if cur: clusters.append(cur)
        for clust in clusters:
            earliest = min(clust, key=lambda x: int(x["Time"][:2])*60 + int(x["Time"][3:]))
            services = sorted({ch for it in clust for ch in it["Services"]})
            result.append({
                "Date": date,
                "Time": earliest["Time"],
                "League": clust[0]["League"],
                "Matchup": earliest["Matchup"],
                "Services": services
            })
    result.sort(key=lambda x: (x["Date"], x["Time"]))
    return result

# ==================== MAIN ====================
def main():
    try:
        # StarHub
        xml_s = download(EPG_URL_STARHUB)
        ch_s = parse_channels_starhub(xml_s)
        m_s = parse_starhub(xml_s, ch_s)
        print(f"⚽🎾 StarHub: {len(m_s)}")

        m_n = parse_nt74(download(EPG_URL_NT74))
        print(f"🎾 nt74: {len(m_n)}")

        m_x = parse_xvb(download(EPG_URL_XVB))
        print(f"🎾 xvb: {len(m_x)}")

        m_pt = parse_epgshare(download_gz(EPG_URL_PT1), 'PT1')
        print(f"🇵🇹 PT1: {len(m_pt)}")

        m_ro = parse_epgshare(download_gz(EPG_URL_RO1), 'RO1')
        print(f"🇷🇴 RO1: {len(m_ro)}")

        all_m = merge_all(m_s, m_n, m_x, m_pt, m_ro)
        print(f"📋 Tổng: {len(all_m)}")

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_m, f, ensure_ascii=False, indent=2)
        print("✅ Hoàn thành!")

    except Exception as e:
        print(f"❌ {e}")
        raise

if __name__ == "__main__":
    main()
