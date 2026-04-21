import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import json
import re
from collections import defaultdict

# ================================================
# SCRIPT LẤY LỊCH TRẬN BÓNG ĐÁ + TENNIS CHÍNH XÁC (PHIÊN BẢN SỬA CUỐI)
# ✅ Chỉ lấy khi có đúng (Live) trong ngoặc
# ✅ Premier League: chỉ khi có đúng 2 đội trong danh sách
# ✅ Matchup sạch sẽ: chỉ còn "Team1 vs Team2"
# ✅ Sửa lỗi "vrpool", "rpool", "- EP xxx", LFCTV...
# ================================================

#EPG_URL = "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml"
EPG_URL = "https://github.com/jeffrybp/epgtv/raw/refs/heads/main/public/all.xml.gz"
OUTPUT_FILE = "live_matches.json"

# ==================== DANH SÁCH ĐỘI PREMIER LEAGUE (chính xác) ====================
PREMIER_LEAGUE_TEAMS = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton", "wolverhampton wanderers"
}

# Map viết tắt phổ biến trong title
TEAM_ABBR = {
    "rpool": "liverpool",
    "man city": "manchester city",
    "man utd": "manchester united",
    "newcastle": "newcastle",
    "wolves": "wolverhampton",
    "fulham": "fulham",
    "everton": "everton",
    # thêm nếu cần
}

def download_xml(url: str) -> str:
    print("📥 Đang tải EPG từ StarHub...")
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    print(f"✅ Tải thành công ({len(response.content):,} bytes)")
    return response.text

def parse_channels(xml_content: str) -> dict:
    root = ET.fromstring(xml_content)
    channels = {}
    for channel in root.findall("channel"):
        chan_id = channel.get("id")
        display_name = channel.findtext("display-name", "").strip()
        if chan_id and display_name:
            channels[chan_id] = display_name
    print(f"📺 Tìm thấy {len(channels)} kênh")
    return channels

def has_exact_live(title: str) -> bool:
    """Chỉ chấp nhận (Live) trong ngoặc, không chấp nhận live lẻ"""
    return bool(re.search(r'\(Live\)', title, re.IGNORECASE))

def is_premier_league(title: str, desc: str) -> bool:
    """Chỉ lấy khi có (Live) + đúng 2 đội Premier League"""
    if not has_exact_live(title):
        return False
    
    text = (title + " " + desc).lower()
    # Thay viết tắt trước khi kiểm tra
    for abbr, full in TEAM_ABBR.items():
        text = text.replace(abbr, full)
    
    found_teams = [team for team in PREMIER_LEAGUE_TEAMS if team in text]
    return len(found_teams) >= 2   # phải có ít nhất 2 đội

def is_tennis(title: str) -> bool:
    """Tennis thật + phải có (Live)"""
    if not has_exact_live(title):
        return False
    
    text = title.lower()
    tennis_keywords = {
        "atp", "wta", "atp tour", "wta tour", "atp world tour",
        "grand slam", "australian open", "roland garros", "french open",
        "wimbledon", "us open", "nitto atp finals",
        "atp masters", "atp 1000", "atp 500", "atp 250",
        "wta 1000", "wta 500", "wta 250",
        "davis cup", "billie jean king cup", "laver cup"
    }
    has_tennis = any(kw in text for kw in tennis_keywords)
    has_padel = "padel" in text or "padbol" in text
    return has_tennis and not has_padel

def clean_football_matchup(title: str) -> str:
    """Chỉ giữ đúng 2 đội, format: Team1 vs Team2"""
    # 1. Xóa (Live), (MW..), - EP xxx, LFCTV...
    title = re.sub(r'\(Live\)', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\(MW\d+\)', '', title, flags=re.IGNORECASE)
    title = re.sub(r'-\s*EP\s*\d+', '', title, flags=re.IGNORECASE)
    title = re.sub(r'LFCTV[^:]*:', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s*:\s*', ' vs ', title)          # thay : thành vs
    title = re.sub(r'\s+', ' ', title).strip()
    
    # 2. Thay viết tắt
    text_lower = title.lower()
    for abbr, full in TEAM_ABBR.items():
        text_lower = text_lower.replace(abbr, full)
    
    # 3. Tìm đúng 2 đội trong danh sách
    found = []
    for team in PREMIER_LEAGUE_TEAMS:
        if team in text_lower:
            found.append(team.title())   # Viết hoa lại đẹp
    
    if len(found) >= 2:
        # Lấy 2 đội đầu tiên xuất hiện
        team1, team2 = found[0], found[1]
        return f"{team1} vs {team2}"
    
    # Fallback nếu không tìm thấy (không nên xảy ra)
    return title

def parse_tennis(title: str) -> tuple[str, str]:
    """Xử lý Tennis giống trước"""
    match = re.search(r'^(ATP|WTA) Tour (\d{4})\s+(.*)$', title.strip(), re.IGNORECASE)
    if match:
        tour = match.group(1).upper()
        year = match.group(2)
        event = match.group(3).strip()
        event = re.sub(r'\(Live\)', '', event, flags=re.IGNORECASE).strip()
        return f"{tour} Tour {year}", event
    
    clean = re.sub(r'\(Live\)', '', title, flags=re.IGNORECASE).strip()
    return "Tennis", clean

def parse_programmes(xml_content: str, channels: dict) -> list:
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

        # ==================== LỌC CHÍNH XÁC ====================
        if is_premier_league(title, desc):
            league = "Premier League"
            matchup = clean_football_matchup(title)
        elif is_tennis(title):
            league, matchup = parse_tennis(title)
        else:
            continue

        # Parse thời gian → UTC+7
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
    print(f"⚽🎾 Tìm thấy {len(output)} trận hợp lệ (Premier League + Tennis)")
    return output

def main():
    try:
        xml_content = download_xml(EPG_URL)
        channels = parse_channels(xml_content)
        matches = parse_programmes(xml_content, channels)

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(matches, f, ensure_ascii=False, indent=2)

        print(f"✅ Hoàn thành! Đã lưu {len(matches)} trận vào {OUTPUT_FILE}")
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        raise

if __name__ == "__main__":
    main()
