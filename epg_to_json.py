import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import json
import re
from collections import defaultdict

# ================================================
# SCRIPT LẤY LỊCH TRẬN BÓNG ĐÁ + TENNIS – 3 NGUỒN
# ✅ StarHub: Premier League + FA Cup (≥1 đội PL) + Tennis, beIN SPORTS → Malaysia
# ✅ nt74/epglist: Tennis, kênh Sport Klub X Hrvatska
# ✅ xvb-lab/xvb-epg: Tennis, kênh ... France
# ================================================

EPG_URL_STARHUB = "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml"
EPG_URL_NT74 = "https://raw.githubusercontent.com/nt74/epglist/refs/heads/main/guide.xml"
EPG_URL_XVB = "https://raw.githubusercontent.com/xvb-lab/xvb-epg/refs/heads/main/epg/epg-fr.xml"
OUTPUT_FILE = "live_matches.json"

# ==================== DANH SÁCH ĐỘI PREMIER LEAGUE ====================
PREMIER_LEAGUE_TEAMS = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton", "wolverhampton wanderers"
}

# Map viết tắt phổ biến
TEAM_ABBR = {
    "rpool": "liverpool",
    "man city": "manchester city",
    "man utd": "manchester united",
    "newcastle": "newcastle",
    "wolves": "wolverhampton",
    "fulham": "fulham",
    "everton": "everton",
}

# ========== TIỆN ÍCH CHUNG ==========
def download_xml(url: str) -> str:
    print(f"📥 Đang tải EPG từ {url.split('/')[-1]}...")
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    print(f"✅ Tải thành công ({len(response.content):,} bytes)")
    return response.text

def has_live_indicator(title: str, desc: str) -> bool:
    """Dùng cho StarHub & nt74: (Live) hoặc (LIVE)"""
    text = f"{title} {desc}".lower()
    return bool(re.search(r'\(live\)', text, re.IGNORECASE))

def has_live_indicator_fr(desc: str) -> bool:
    """Dùng cho xvb: En Direct"""
    return bool(re.search(r'en\s+direct', desc, re.IGNORECASE))

# ========== BÓNG ĐÁ (StarHub) ==========
def is_fa_cup(title: str) -> bool:
    """Kiểm tra title có chứa FA Cup"""
    return bool(re.search(r'\bFA\s+Cup\b', title, re.IGNORECASE))

def has_any_premier_league_team(text: str) -> bool:
    """Kiểm tra có ít nhất 1 đội trong danh sách PL"""
    lower_text = text.lower()
    for abbr, full in TEAM_ABBR.items():
        lower_text = lower_text.replace(abbr, full)
    return any(team in lower_text for team in PREMIER_LEAGUE_TEAMS)

def is_premier_league(title: str, desc: str) -> bool:
    """Lấy Premier League: có (Live) + đủ 2 đội PL + không phải FA Cup"""
    if not has_live_indicator(title, desc):
        return False
    if is_fa_cup(title):  # FA Cup sẽ được xử lý riêng
        return False
    text = (title + " " + desc).lower()
    for abbr, full in TEAM_ABBR.items():
        text = text.replace(abbr, full)
    found_teams = [team for team in PREMIER_LEAGUE_TEAMS if team in text]
    return len(found_teams) >= 2

def clean_football_matchup(title: str) -> str:
    """Làm sạch title (Premier League hoặc FA Cup) chỉ giữ lại Tên đội 1 vs Tên đội 2"""
    # Loại bỏ (Live)
    title = re.sub(r'\(Live\)', '', title, flags=re.IGNORECASE)
    # Loại bỏ các tiền tố FA Cup phổ biến
    title = re.sub(r'(?:The\s+)?Emirates\s+FA\s+Cup\s+\d{4}/\d{2}\s+SF:\s*', '', title, flags=re.IGNORECASE)
    title = re.sub(r'FA\s+Cup\s+\d{4}/\d{2}\s+SF:\s*', '', title, flags=re.IGNORECASE)
    title = re.sub(r'FA\s+Cup:\s*', '', title, flags=re.IGNORECASE)
    # Loại bỏ các tag khác (MW, EP, LFCTV...)
    title = re.sub(r'\(MW\d+\)', '', title, flags=re.IGNORECASE)
    title = re.sub(r'-\s*EP\s*\d+', '', title, flags=re.IGNORECASE)
    title = re.sub(r'LFCTV[^:]*:', '', title, flags=re.IGNORECASE)
    # Thay dấu ':' còn sót thành ' vs '
    title = re.sub(r'\s*:\s*', ' vs ', title)
    title = re.sub(r'\s+', ' ', title).strip()

    # Thay viết tắt
    text_lower = title.lower()
    for abbr, full in TEAM_ABBR.items():
        text_lower = text_lower.replace(abbr, full)

    # Tìm 2 đội trong danh sách PL (ưu tiên)
    found = [team.title() for team in PREMIER_LEAGUE_TEAMS if team in text_lower]
    if len(found) >= 2:
        return f"{found[0]} vs {found[1]}"
    elif len(found) == 1:
        # FA Cup có thể chỉ có 1 đội PL, giữ nguyên phần còn lại làm tên đối thủ
        # Tạm thời trả về dạng "Đội PL vs Đối thủ" bằng cách dùng phần còn lại sau khi loại bỏ đội đã biết
        # Nhưng để an toàn, giữ nguyên title sạch (có thể là "Chelsea vs Leeds United AFC")
        # Tuy nhiên nếu đã tìm thấy 1 đội PL, ta có thể cố gắng tách bằng "vs"
        parts = [p.strip() for p in title.split(' vs ', 1)]
        if len(parts) == 2:
            return f"{parts[0]} vs {parts[1]}"
        # Fallback
        return title
    else:
        # Không tìm thấy đội PL nào (hiếm), trả về title sạch
        return title

# ========== TENNIS CHUNG ==========
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

# ========== ĐỊNH DẠNG TÊN KÊNH THEO NGUỒN ==========
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

        # 1. FA Cup (ưu tiên cao nhất)
        if is_fa_cup(title) and has_live_indicator(title, desc):
            if has_any_premier_league_team(title + " " + desc):
                league = "FA Cup"
                matchup = clean_football_matchup(title)
        # 2. Premier League
        elif is_premier_league(title, desc):
            league = "Premier League"
            matchup = clean_football_matchup(title)
        # 3. Tennis
        elif is_tennis_title(title) and has_live_indicator(title, desc):
            league, matchup = parse_tennis_matchup(title)
        else:
            continue

        # Parse thời gian
        try:
            dt_utc = datetime.strptime(start_str, "%Y%m%d%H%M%S %z")
        except ValueError:
            dt_naive = datetime.strptime(start_str[:14], "%Y%m%d%H%M%S")
            dt_utc = dt_naive.replace(tzinfo=timezone.utc)
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
        try:
            dt_utc = datetime.strptime(start_str, "%Y%m%d%H%M%S %z")
        except ValueError:
            dt_naive = datetime.strptime(start_str[:14], "%Y%m%d%H%M%S")
            dt_utc = dt_naive.replace(tzinfo=timezone.utc)
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
        try:
            dt_utc = datetime.strptime(start_str, "%Y%m%d%H%M%S %z")
        except ValueError:
            dt_naive = datetime.strptime(start_str[:14], "%Y%m%d%H%M%S")
            dt_utc = dt_naive.replace(tzinfo=timezone.utc)
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
        print(f"⚽🎾 StarHub: {len(matches_starhub)} trận (PL + FA Cup + Tennis)")

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
