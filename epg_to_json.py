import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import json
import re
from collections import defaultdict

# ================================================
# SCRIPT TỰ ĐỘNG LẤY LỊCH TRẬN BÓNG ĐÁ + TENNIS
# CHỈ LẤY: Premier League (Ngoại hạng Anh) + Tennis
# Chạy trên GitHub Workflow - output live_matches.json
# ================================================

EPG_URL = "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml"
OUTPUT_FILE = "live_matches.json"

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
    """Kiểm tra có phải Premier League không"""
    text = (title + " " + desc).lower()
    return "premier league" in text or "epl" in text

def is_tennis(title: str) -> bool:
    """Kiểm tra có phải Tennis không (ATP/WTA)"""
    text = title.lower()
    tennis_keywords = ["atp", "wta", "tennis", "open", "masters", "sf ", "final ", "semifinal", "quarterfinal"]
    return any(kw in text for kw in tennis_keywords)

def clean_football_matchup(title: str) -> str:
    """Làm sạch tên trận Ngoại hạng Anh → chỉ còn 2 đội"""
    # Xóa (Live), (MWxx), ...
    title = re.sub(r"\s*\(Live\)", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\(MW\d+\)", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\(.*?\)", "", title)                    # xóa tất cả ngoặc
    title = re.sub(r"\s*Live[: ]*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip()
    return title

def parse_tennis(title: str) -> tuple[str, str]:
    """Xử lý Tennis theo yêu cầu:
       League: "ATP Tour 2026"
       Matchup: "Barcelona Open Banc Sabadell SF 2"
    """
    # Regex bắt đầu bằng ATP/WTA Tour + năm
    match = re.search(r'^(ATP|WTA) Tour (\d{4})\s+(.*)$', title.strip(), re.IGNORECASE)
    if match:
        tour = match.group(1).upper()
        year = match.group(2)
        event = match.group(3).strip()
        league = f"{tour} Tour {year}"
        matchup = event
        return league, matchup
    
    # Fallback nếu không khớp exact pattern
    return "Tennis", title.strip()

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
        if not (is_premier_league(title, desc) or is_tennis(title)):
            continue

        # Parse thời gian → giờ Việt Nam (UTC+7)
        try:
            dt_utc = datetime.strptime(start_str, "%Y%m%d%H%M%S %z")
        except ValueError:
            dt_naive = datetime.strptime(start_str[:14], "%Y%m%d%H%M%S")
            dt_utc = dt_naive.replace(tzinfo=timezone.utc)

        dt_vn = dt_utc + timedelta(hours=7)
        date_str = dt_vn.strftime("%Y-%m-%d")
        time_str = dt_vn.strftime("%H:%M")

        channel_name = channels.get(channel_id, f"Channel {channel_id}")

        # ==================== XỬ LÝ PREMIER LEAGUE ====================
        if is_premier_league(title, desc):
            league = "Premier League"
            matchup = clean_football_matchup(title)
        
        # ==================== XỬ LÝ TENNIS ====================
        else:
            league, matchup = parse_tennis(title)

        # Key nhóm trận giống nhau
        key = (date_str, time_str, matchup.lower())

        groups[key].append({
            "channel": channel_name,
            "league": league,
            "matchup": matchup,
            "date": date_str,
            "time": time_str,
        })

    # Xây dựng JSON output
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

    # Sắp xếp theo thời gian
    output.sort(key=lambda x: (x["Date"], x["Time"]))
    print(f"⚽ Tìm thấy {len(output)} trận (Premier League + Tennis)")
    return output

def main():
    try:
        xml_content = download_xml(EPG_URL)
        channels = parse_channels(xml_content)
        matches = parse_programmes(xml_content, channels)

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(matches, f, ensure_ascii=False, indent=2)

        print(f"✅ Hoàn thành! Đã lưu {len(matches)} trận vào {OUTPUT_FILE}")
        print(f"📂 File sẵn sàng commit vào GitHub repo")

    except Exception as e:
        print(f"❌ Lỗi: {e}")
        raise

if __name__ == "__main__":
    main()
