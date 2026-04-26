import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import json
import re
from collections import defaultdict

# ================================================
# SCRIPT LẤY LỊCH TRẬN BÓNG ĐÁ + TENNIS (3 nguồn)
# ✅ Sửa lỗi Wolverhampton trùng lặp
# ✅ Chỉ giữ trận từ -6h đến +72h tính từ lúc chạy
# ================================================

EPG_URL_STARHUB = "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml"
EPG_URL_NT74 = "https://raw.githubusercontent.com/nt74/epglist/refs/heads/main/guide.xml"
EPG_URL_XVB = "https://raw.githubusercontent.com/xvb-lab/xvb-epg/refs/heads/main/epg/epg-fr.xml"
OUTPUT_FILE = "live_matches.json"

# Khoảng thời gian cho phép (giờ)
HOURS_BEFORE = 6
HOURS_AFTER = 72

# ==================== DANH SÁCH ĐỘI PREMIER LEAGUE ====================
PREMIER_LEAGUE_TEAMS = [
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton wanderers", "wolverhampton"
]
# Sắp xếp theo độ dài giảm dần để ưu tiên tên đầy đủ
PREMIER_LEAGUE_TEAMS.sort(key=len, reverse=True)

TEAM_ABBR = {
    "rpool": "liverpool",
    "man city": "manchester city",
    "man utd": "manchester united",
    "newcastle": "newcastle",
    "wolves": "wolverhampton wanderers",
    "fulham": "fulham",
    "everton": "everton",
}

# ========== TIỆN ÍCH CHUNG ==========
def download_xml(url: str) -> str:
    print(f"📥 Đang tải EPG từ {url.split('/')[-1]}...")
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    print(f"✅ Tải thành công ({len(response.content):,} bytes)")
    return response.text

def has_live_indicator(title: str, desc: str) -> bool:
    text = f"{title} {desc}".lower()
    return bool(re.search(r'\(live\)', text, re.IGNORECASE))

def has_live_indicator_fr(desc: str) -> bool:
    return bool(re.search(r'en\s+direct', desc, re.IGNORECASE))

# ========== BÓNG ĐÁ ==========
def is_fa_cup(title: str) -> bool:
    return bool(re.search(r'\bFA\s+Cup\b', title, re.IGNORECASE))

def extract_teams(text: str) -> list:
    """Trả về danh sách tên đội PL tìm thấy, không chứa tên con của nhau"""
    lower_text = text.lower()
    for abbr, full in TEAM_ABBR.items():
        lower_text = lower_text.replace(abbr, full)

    found = []
    for team in PREMIER_LEAGUE_TEAMS:
        if team in lower_text:
            # Chỉ thêm nếu không có tên dài hơn đã tồn tại chứa team này
            if not any(team != existing and team in existing for existing in found):
                found.append(team)
    return found

def is_premier_league(title: str, desc: str) -> bool:
    if not has_live_indicator(title, desc):
        return False
    if is_fa_cup(title):
        return False
    teams = extract_teams(title + " " + desc)
    return len(teams) >= 2

def clean_football_matchup(title: str) -> str:
    # Xóa các tag không cần thiết
    title = re.sub(r'\(Live\)', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\(MW\d+\)', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\(Goal\s*Rush\)', '', title, flags=re.IGNORECASE)
    title = re.sub(r'-\s*EP\s*\d+', '', title, flags=re.IGNORECASE)
    title = re.sub(r'LFCTV[^:]*:', '', title, flags=re.IGNORECASE)
    # Chuẩn hóa ' v ' thành ' vs '
    title = re.sub(r'\s+v\s+', ' vs ', title)
    title = re.sub(r'\s+', ' ', title).strip()

    teams = extract_teams(title)
    if len(teams) >= 2:
        # Xác định thứ tự xuất hiện trong tiêu đề
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

# ========== TENNIS ==========
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
    clean_title = re.sub(r'^(Tennis|Tenis)\s*:\s*', '', clean_title, flags=re.IGNORECASE).strip()
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

# ========== ĐỊNH DẠNG TÊN KÊNH ==========
def format_starhub_channel_name(name: str) -> str:
    if re.search(r'bein\s*sports', name, re.IGNORECASE):
        return f"{name} Malaysia"
    return name

def format_channel_name_nt74(channel_id: str) -> str:
    match = re.match(r'sportklub(\d+)\.rs', channel_id, re.IGNORECASE)
    if match:
        return f"Sport Klub {match.group(1)} Hrvatska"
    return channel_id.replace('.rs', '').upper()

def format_channel_name_xvb(channel_id: str) -> str:
    name = re.sub(r'\.fr$', '', channel_id, flags=re.IGNORECASE)
    name = name.replace('.', ' ')
    name = name.title()
    name = re.sub(r'\bBein\b', 'beIN', name)
    return f"{name} France"

# ========== KIỂM TRA THỜI GIAN ==========
def is_within_time_window(start_utc: datetime, now_utc: datetime) -> bool:
    lower = now_utc - timedelta(hours=HOURS_BEFORE)
    upper = now_utc + timedelta(hours=HOURS_AFTER)
    return lower <= start_utc <= upper

def parse_and_filter_time(start_str: str, raw_offset: str = None) -> datetime or None:
    """Parse start_str thành UTC datetime. raw_offset dùng nếu cần."""
    try:
        # Định dạng có offset
        dt_utc = datetime.strptime(start_str, "%Y%m%d%H%M%S %z")
    except ValueError:
        # Fallback: bỏ qua offset, coi là UTC
        dt_naive = datetime.strptime(start_str[:14], "%Y%m%d%H%M%S")
        dt_utc = dt_naive.replace(tzinfo=timezone.utc)
    return dt_utc

# ========== PARSE TỪNG NGUỒN ==========
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

        # FA Cup
        if is_fa_cup(title) and has_live_indicator(title, desc):
            if extract_teams(title + " " + desc):
                league = "FA Cup"
                matchup = clean_football_matchup(title)
        # Premier League
        elif is_premier_league(title, desc):
            league = "Premier League"
            matchup = clean_football_matchup(title)
        # Tennis
        elif is_tennis_title(title) and has_live_indicator(title, desc):
            league, matchup = parse_tennis_matchup(title)
        else:
            continue

        # Kiểm tra thời gian
        dt_utc = parse_and_filter_time(start_str)
        if not is_within_time_window(dt_utc, now_utc):
            continue

        dt_vn = dt_utc + timedelta(hours=7)
        date_str = dt_vn.strftime("%Y-%m-%d")
        time_str = dt_vn.strftime("%H:%M")

        raw_name = channels.get(channel_id, f"Channel {channel_id}")
        channel_name = format_starhub_channel_name(raw_name)

        key = (date_str, time_str, matchup.lower())
        groups[key].append({
            "channel": channel_name,
            "league": league,
            "matchup": matchup,
            "date": date_str,
            "time": time_str,
        })

    return _groups_to_output(groups)

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

        if not (is_tennis_title(title) and has_live_indicator(title, desc)):
            continue

        league, matchup = parse_tennis_matchup(title)

        dt_utc = parse_and_filter_time(start_str)
        if not is_within_time_window(dt_utc, now_utc):
            continue

        dt_vn = dt_utc + timedelta(hours=7)
        date_str = dt_vn.strftime("%Y-%m-%d")
        time_str = dt_vn.strftime("%H:%M")

        channel_name = format_channel_name_nt74(channel_id) if channel_id else "Unknown"
        key = (date_str, time_str, matchup.lower())
        groups[key].append({
            "channel": channel_name,
            "league": league,
            "matchup": matchup,
            "date": date_str,
            "time": time_str,
        })

    return _groups_to_output(groups)

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

        dt_utc = parse_and_filter_time(start_str)
        if not is_within_time_window(dt_utc, now_utc):
            continue

        dt_vn = dt_utc + timedelta(hours=7)
        date_str = dt_vn.strftime("%Y-%m-%d")
        time_str = dt_vn.strftime("%H:%M")

        channel_name = format_channel_name_xvb(channel_id) if channel_id else "Unknown"
        key = (date_str, time_str, matchup.lower())
        groups[key].append({
            "channel": channel_name,
            "league": league,
            "matchup": matchup,
            "date": date_str,
            "time": time_str,
        })

    return _groups_to_output(groups)

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

# ========== MAIN ==========
def main():
    try:
        xml_starhub = download_xml(EPG_URL_STARHUB)
        channels_starhub = parse_channels_starhub(xml_starhub)
        matches_starhub = parse_programmes_starhub(xml_starhub, channels_starhub)
        print(f"⚽🎾 StarHub: {len(matches_starhub)} trận (trong khung giờ)")

        xml_nt74 = download_xml(EPG_URL_NT74)
        matches_nt74 = parse_programmes_nt74(xml_nt74)
        print(f"🎾 nt74: {len(matches_nt74)} trận")

        xml_xvb = download_xml(EPG_URL_XVB)
        matches_xvb = parse_programmes_xvb(xml_xvb)
        print(f"🎾 xvb (France): {len(matches_xvb)} trận")

        all_matches = merge_match_lists(matches_starhub, matches_nt74, matches_xvb)
        print(f"📋 Tổng sau gộp: {len(all_matches)} trận")

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_matches, f, ensure_ascii=False, indent=2)

        print(f"✅ Hoàn thành! Đã lưu {OUTPUT_FILE}")

    except Exception as e:
        print(f"❌ Lỗi: {e}")
        raise

if __name__ == "__main__":
    main()
