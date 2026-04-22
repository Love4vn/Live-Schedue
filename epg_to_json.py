import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import json
import re
from collections import defaultdict

# ================================================
# SCRIPT LẤY LỊCH TRẬN BÓNG ĐÁ + TENNIS CHÍNH XÁC
# ✅ Tích hợp 2 nguồn EPG:
#   1. StarHub (Premier League + Tennis)
#   2. nt74/epglist (chỉ Tennis)
# ✅ Chỉ lấy khi có (Live) hoặc (LIVE)
# ✅ Matchup sạch sẽ, League rõ ràng
# ✅ Tên kênh nt74 hiển thị: Sport Klub X Hrvatska
# ================================================

EPG_URL_STARHUB = "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml"
EPG_URL_NT74 = "https://raw.githubusercontent.com/nt74/epglist/refs/heads/main/guide.xml"
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

def download_xml(url: str) -> str:
    print(f"📥 Đang tải EPG từ {url.split('/')[-1]}...")
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    print(f"✅ Tải thành công ({len(response.content):,} bytes)")
    return response.text

def has_live_indicator(title: str, desc: str) -> bool:
    """Kiểm tra có (Live) hoặc (LIVE) trong title hoặc desc"""
    text = f"{title} {desc}".lower()
    return bool(re.search(r'\(live\)', text, re.IGNORECASE))

def is_premier_league(title: str, desc: str) -> bool:
    """Chỉ lấy khi có Live + đúng 2 đội Premier League (dùng cho StarHub)"""
    if not has_live_indicator(title, desc):
        return False

    text = (title + " " + desc).lower()
    for abbr, full in TEAM_ABBR.items():
        text = text.replace(abbr, full)

    found_teams = [team for team in PREMIER_LEAGUE_TEAMS if team in text]
    return len(found_teams) >= 2

def is_tennis(title: str, desc: str) -> bool:
    """Tennis có Live (dùng cho cả hai nguồn)"""
    if not has_live_indicator(title, desc):
        return False

    text = title.lower()
    tennis_keywords = {
        "atp", "wta", "tenis", "atp tour", "wta tour", "grand slam",
        "australian open", "roland garros", "french open", "wimbledon", "us open",
        "madrid open", "mutua madrid", "davis cup", "laver cup"
    }
    has_tennis = any(kw in text for kw in tennis_keywords)
    has_padel = "padel" in text or "padbol" in text
    return has_tennis and not has_padel

def clean_football_matchup(title: str) -> str:
    """Xử lý riêng cho Premier League"""
    title = re.sub(r'\(Live\)', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\(MW\d+\)', '', title, flags=re.IGNORECASE)
    title = re.sub(r'-\s*EP\s*\d+', '', title, flags=re.IGNORECASE)
    title = re.sub(r'LFCTV[^:]*:', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s*:\s*', ' vs ', title)
    title = re.sub(r'\s+', ' ', title).strip()

    text_lower = title.lower()
    for abbr, full in TEAM_ABBR.items():
        text_lower = text_lower.replace(abbr, full)

    found = []
    for team in PREMIER_LEAGUE_TEAMS:
        if team in text_lower:
            found.append(team.title())

    if len(found) >= 2:
        team1, team2 = found[0], found[1]
        return f"{team1} vs {team2}"
    return title

def parse_tennis_matchup(title: str) -> tuple[str, str]:
    """
    Tách League và Matchup từ title Tennis.
    Hỗ trợ:
      - "ATP Masters Madrid: Basilashvili - Ofner"
      - "WTA 1000 Madrid: Selekhmeteva - Jeanjean"
      - "Tenis: WTA 1000 & ATP Masters Madrid"
    """
    # Xóa (Live) nếu có
    clean_title = re.sub(r'\(Live\)', '', title, flags=re.IGNORECASE).strip()

    # Nếu có dấu ":" và phần trước ":" chứa từ khóa tennis
    if ":" in clean_title:
        parts = clean_title.split(":", 1)
        league_candidate = parts[0].strip()
        matchup_candidate = parts[1].strip()
        if any(kw in league_candidate.lower() for kw in ["atp", "wta", "tenis"]):
            return league_candidate, matchup_candidate

    # Fallback: tìm giải đấu dựa trên từ khóa
    text = clean_title.lower()
    if "atp masters" in text:
        league = "ATP Masters"
    elif "wta 1000" in text:
        league = "WTA 1000"
    elif "atp" in text:
        league = "ATP"
    elif "wta" in text:
        league = "WTA"
    else:
        league = "Tennis"

    return league, clean_title

def parse_channels(xml_content: str) -> dict:
    """Lấy ánh xạ channel id -> display-name (cho StarHub)"""
    root = ET.fromstring(xml_content)
    channels = {}
    for channel in root.findall("channel"):
        chan_id = channel.get("id")
        display_name = channel.findtext("display-name", "").strip()
        if chan_id and display_name:
            channels[chan_id] = display_name
    print(f"📺 Tìm thấy {len(channels)} kênh")
    return channels

def parse_programmes_starhub(xml_content: str, channels: dict) -> list:
    """Parse EPG StarHub, lấy Premier League + Tennis"""
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

        if is_premier_league(title, desc):
            league = "Premier League"
            matchup = clean_football_matchup(title)
        elif is_tennis(title, desc):
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

        channel_name = channels.get(channel_id, f"Channel {channel_id}")

        key = (date_str, time_str, matchup.lower())
        groups[key].append({
            "channel": channel_name,
            "league": league,
            "matchup": matchup,
            "date": date_str,
            "time": time_str,
        })

    return _groups_to_output(groups)

def format_channel_name_nt74(channel_id: str) -> str:
    """Chuyển đổi channel_id từ nt74 thành tên hiển thị đẹp.
       Ví dụ: sportklub5.rs -> Sport Klub 5 Hrvatska
    """
    match = re.match(r'sportklub(\d+)\.rs', channel_id, re.IGNORECASE)
    if match:
        num = match.group(1)
        return f"Sport Klub {num} Hrvatska"
    # Fallback: bỏ đuôi .rs và viết hoa
    return channel_id.replace('.rs', '').upper()

def parse_programmes_nt74(xml_content: str) -> list:
    """Parse EPG nt74, chỉ lấy Tennis (có (LIVE) trong desc)"""
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

        if not is_tennis(title, desc):
            continue

        league, matchup = parse_tennis_matchup(title)

        # Parse thời gian (có offset +0000)
        try:
            dt_utc = datetime.strptime(start_str, "%Y%m%d%H%M%S %z")
        except ValueError:
            # fallback nếu thiếu offset
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

def _groups_to_output(groups: dict) -> list:
    """Chuyển dict nhóm thành list JSON chuẩn"""
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

def merge_match_lists(list1: list, list2: list) -> list:
    """Hợp nhất hai danh sách trận, gom nhóm lại nếu trùng (Date, Time, Matchup)"""
    merged = defaultdict(list)

    for item in list1 + list2:
        key = (item["Date"], item["Time"], item["Matchup"].lower())
        merged[key].append(item)

    final_output = []
    for (date, time, _), items in merged.items():
        # Lấy League từ item đầu tiên (ưu tiên item có League không rỗng)
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

def main():
    try:
        # --- Nguồn 1: StarHub ---
        xml_starhub = download_xml(EPG_URL_STARHUB)
        channels_starhub = parse_channels(xml_starhub)
        matches_starhub = parse_programmes_starhub(xml_starhub, channels_starhub)
        print(f"⚽🎾 StarHub: {len(matches_starhub)} trận hợp lệ")

        # --- Nguồn 2: nt74 (chỉ Tennis) ---
        xml_nt74 = download_xml(EPG_URL_NT74)
        matches_nt74 = parse_programmes_nt74(xml_nt74)
        print(f"🎾 nt74: {len(matches_nt74)} trận Tennis")

        # --- Hợp nhất ---
        all_matches = merge_match_lists(matches_starhub, matches_nt74)
        print(f"📋 Tổng cộng sau khi gộp: {len(all_matches)} trận")

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_matches, f, ensure_ascii=False, indent=2)

        print(f"✅ Hoàn thành! Đã lưu vào {OUTPUT_FILE}")

    except Exception as e:
        print(f"❌ Lỗi: {e}")
        raise

if __name__ == "__main__":
    main()
