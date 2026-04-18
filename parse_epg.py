import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import json
import re
import os
from collections import defaultdict

# URL của file EPG
EPG_URL = "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml"
OUTPUT_FILE = "live_matches.json"  # Thay đổi đường dẫn nếu cần

def download_xml(url):
    """Tải nội dung XML từ URL."""
    response = requests.get(url)
    response.raise_for_status()
    return response.text

def parse_channels(xml_content):
    """Trả về dict mapping channel id -> display-name."""
    root = ET.fromstring(xml_content)
    channels = {}
    for channel in root.findall("channel"):
        chan_id = channel.get("id")
        display_name = channel.findtext("display-name")
        if chan_id and display_name:
            channels[chan_id] = display_name
    return channels

def parse_programmes(xml_content, channels):
    """Duyệt programme, lọc trận live và trả về danh sách các dict đã nhóm."""
    root = ET.fromstring(xml_content)
    # Nhóm theo (date, time, matchup)
    groups = defaultdict(list)

    for prog in root.findall("programme"):
        channel_id = prog.get("channel")
        start_str = prog.get("start")
        title_elem = prog.find("title")
        desc_elem = prog.find("desc")

        if title_elem is None:
            continue

        title = title_elem.text or ""
        desc = desc_elem.text if desc_elem is not None else ""

        # Chỉ quan tâm chương trình có từ "Live" trong tiêu đề (có thể mở rộng)
        if "Live" not in title:
            continue

        # Parse thời gian start (định dạng YYYYMMDDHHMMSS +0000)
        # Ví dụ: "20260418112000 +0000"
        try:
            dt_utc = datetime.strptime(start_str, "%Y%m%d%H%M%S %z")
        except ValueError:
            # Fallback nếu thiếu %z
            dt_naive = datetime.strptime(start_str[:14], "%Y%m%d%H%M%S")
            dt_utc = dt_naive.replace(tzinfo=timezone.utc)

        # Chuyển sang giờ Việt Nam (UTC+7)
        dt_vn = dt_utc + timedelta(hours=7)
        date_str = dt_vn.strftime("%Y-%m-%d")
        time_str = dt_vn.strftime("%H:%M")

        # Lấy tên kênh từ mapping
        channel_name = channels.get(channel_id, f"Channel {channel_id}")

        # Trích xuất giải đấu (League)
        # Có thể lấy từ title hoặc desc. Mặc định để "Premier League" nếu không rõ.
        league = "Premier League"  # giá trị mặc định
        # Tìm trong title các từ khóa giải đấu
        league_patterns = [
            (r"Premier League", "Premier League"),
            (r"Champions League", "UEFA Champions League"),
            (r"Europa League", "UEFA Europa League"),
            (r"FA Cup", "FA Cup"),
            (r"Carabao Cup", "Carabao Cup"),
            (r"La Liga", "La Liga"),
            (r"Serie A", "Serie A"),
            (r"Bundesliga", "Bundesliga"),
            (r"Ligue 1", "Ligue 1"),
        ]
        for pattern, name in league_patterns:
            if re.search(pattern, title, re.IGNORECASE) or re.search(pattern, desc, re.IGNORECASE):
                league = name
                break

        # Làm sạch tên trận đấu (matchup)
        # Thường title dạng "Team A v Team B (MW...) (Live)" hoặc "Team A v Team B - Premier League (Live)"
        # Loại bỏ phần giải đấu và "(Live)"
        matchup = title
        # Xóa "(Live)" và biến thể
        matchup = re.sub(r"\s*\(Live\)", "", matchup, flags=re.IGNORECASE).strip()
        matchup = re.sub(r"\s*Live:", "", matchup, flags=re.IGNORECASE).strip()
        # Xóa các thông tin vòng đấu như (MW33) hoặc (Quarter-Final)
        matchup = re.sub(r"\s*\(MW\d+\)", "", matchup, flags=re.IGNORECASE).strip()
        # Nếu còn chứa tên giải đấu, có thể loại bỏ sau dấu "-"
        if " - " in matchup:
            matchup = matchup.split(" - ")[0].strip()

        # Key để nhóm: cùng ngày, giờ và tên trận đấu (đã chuẩn hóa)
        key = (date_str, time_str, matchup.lower())
        groups[key].append({
            "channel": channel_name,
            "league": league,
            "matchup": matchup,
            "date": date_str,
            "time": time_str,
        })

    # Tạo output list
    output = []
    for (date, time, _), items in groups.items():
        # Lấy thông tin chung từ item đầu tiên (league, matchup)
        first = items[0]
        services = sorted(set(item["channel"] for item in items))
        output.append({
            "Date": date,
            "Time": time,
            "League": first["league"],
            "Matchup": first["matchup"],
            "Services": services
        })

    # Sắp xếp theo ngày giờ tăng dần
    output.sort(key=lambda x: (x["Date"], x["Time"]))
    return output

def main():
    print("Đang tải EPG...")
    xml_content = download_xml(EPG_URL)
    print("Đang phân tích channels...")
    channels = parse_channels(xml_content)
    print("Đang phân tích programmes...")
    matches = parse_programmes(xml_content, channels)

    # Lưu file JSON
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(matches, f, ensure_ascii=False, indent=4)

    print(f"Đã lưu {len(matches)} trận đấu vào {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
