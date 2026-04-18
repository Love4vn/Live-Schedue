import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import json
import re
from collections import defaultdict

# ================================================
# SCRIPT LẤY LỊCH TRẬN BÓNG ĐÁ + TENNIS CHÍNH XÁC
# Chỉ lấy:
#   • Premier League (chỉ khi có tên đội thật)
#   • Tennis ATP / WTA (loại bỏ Padel, Padbol...)
# ================================================

EPG_URL = "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml"
OUTPUT_FILE = "live_matches.json"

# ==================== DANH SÁCH ĐỘI PREMIER LEAGUE ====================
PREMIER_LEAGUE_TEAMS = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton", "wolverhampton wanderers"
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

def is_premier_league(title: str, desc: str) -> bool:
    """Chỉ lấy khi có tên đội Premier League + chữ Live"""
    if "Live" not in title:
        return False
    text = (title + " " + desc).lower()
    return any(team in text for team in PREMIER_LEAGUE_TEAMS)

def is_tennis(title: str) -> bool:
    """Lọc Tennis thật (ATP/WTA) – loại bỏ Padel, Padbol..."""
    if "Live" not in title:
        return False
    text = title.lower()
    
    tennis_keywords = {
        "atp", "wta", "atp tour", "wta tour", "atp world tour",
        "grand slam", "australian open", "roland garros", "french open",
        "wimbledon", "us open", "nitto atp finals",
        "atp masters", "atp 1000", "atp 500", "atp 250",
        "wta 1000", "wta 500", "wta 250",
        "davis cup", "billie jean king cup", "fed cup", "laver cup", "hopman cup"
    }
    
    # Phải chứa ít nhất 1 từ khóa tennis
    has_tennis = any(kw in text for kw in tennis_keywords)
    # Loại bỏ hoàn toàn Padel, Padbol, Premier Padel
    has_padel = "padel" in text or "padbol" in text
    
    return has_tennis and not has_padel

def clean_football_matchup(title: str) -> str:
    """Chỉ giữ tên 2 đội"""
    title = re.sub(r"\s*\(Live\)", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\(MW\d+\)", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\(.*?\)", "", title)
    title = re.sub(r"\s*Live[: ]*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip()
    return title

def parse_tennis(title: str) -> tuple[str, str]:
    """League = ATP Tour 2026 / WTA Tour 2026
       Matchup = phần sau sạch sẽ"""
    # Bắt pattern ATP/WTA Tour + năm
    match = re.search(r'^(ATP|WTA) Tour (\d{4})\s+(.*)$', title.strip(), re.IGNORECASE)
    if match:
        tour = match.group(1).upper()
        year = match.group(2)
        event = match.group(3).strip()
        # Làm sạch event
        event = re.sub(r"\s*\(Live\)", "", event, flags=re.IGNORECASE).strip()
        return f"{tour} Tour {year}", event
    
    # Fallback
    clean = re.sub(r"\s*\(Live\)", "", title, flags=re.IGNORECASE).strip()
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

        # ==================== LỌC CHỈ PREMIER LEAGUE + TENNIS ====================
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

    # Xây dựng JSON
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
