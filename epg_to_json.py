import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import json
import re
from collections import defaultdict

# ================================================
# SCRIPT TỰ ĐỘNG LẤY LỊCH TRẬN BÓNG ĐÁ TRỰC TIẾP
# Chạy được trên GitHub Workflow (không cần server)
# Nguồn EPG: StarHub TV (cập nhật realtime)
# Output: live_matches.json (commit trực tiếp vào repo)
# ================================================

EPG_URL = "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml"
OUTPUT_FILE = "live_matches.json"

def download_xml(url: str) -> str:
    """Tải file XML EPG"""
    print("📥 Đang tải EPG từ StarHub...")
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    print(f"✅ Tải thành công ({len(response.content):,} bytes)")
    return response.text

def parse_channels(xml_content: str) -> dict:
    """Lấy danh sách kênh (id → display-name)"""
    root = ET.fromstring(xml_content)
    channels = {}
    for channel in root.findall("channel"):
        chan_id = channel.get("id")
        display_name = channel.findtext("display-name", "").strip()
        if chan_id and display_name:
            channels[chan_id] = display_name
    print(f"📺 Tìm thấy {len(channels)} kênh")
    return channels

def clean_matchup(title: str) -> str:
    """Làm sạch tên trận đấu"""
    # Xóa (Live), (MWxx), (Highlight), ...
    title = re.sub(r"\s*\(Live\)", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\(MW\d+\)", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\(.*?\)", "", title)          # xóa tất cả ngoặc
    title = re.sub(r"\s*Live[: ]*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip()
    return title

def detect_league(title: str, desc: str) -> str:
    """Nhận diện giải đấu (ưu tiên desc → title)"""
    text = (desc or "") + " " + (title or "")
    patterns = [
        (r"Premier League|EPL", "Premier League"),
        (r"Champions League|UEFA CL", "UEFA Champions League"),
        (r"Europa League|UEFA EL", "UEFA Europa League"),
        (r"FA Cup", "FA Cup"),
        (r"Carabao Cup", "Carabao Cup"),
        (r"La Liga", "La Liga"),
        (r"Serie A", "Serie A"),
        (r"Bundesliga", "Bundesliga"),
        (r"Ligue 1", "Ligue 1"),
        (r"MLS|Major League Soccer", "Major League Soccer"),
        (r"World Cup|WC", "FIFA World Cup"),
        (r"Asian Cup|AFC", "AFC Asian Cup"),
        (r"SEA Games", "SEA Games"),
        (r"V.League", "V.League"),
    ]
    text_lower = text.lower()
    for pattern, league_name in patterns:
        if re.search(pattern, text_lower):
            return league_name
    return "Other League"   # fallback rõ ràng

def parse_programmes(xml_content: str, channels: dict) -> list:
    """Phân tích các trận Live"""
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

        # Chỉ lấy trận có chữ "Live"
        if "Live" not in title:
            continue

        # Parse thời gian (định dạng StarHub: 20260418112000 +0000)
        try:
            dt_utc = datetime.strptime(start_str, "%Y%m%d%H%M%S %z")
        except ValueError:
            # fallback nếu không có timezone
            dt_naive = datetime.strptime(start_str[:14], "%Y%m%d%H%M%S")
            dt_utc = dt_naive.replace(tzinfo=timezone.utc)

        # Chuyển sang giờ Việt Nam (UTC+7)
        dt_vn = dt_utc + timedelta(hours=7)
        date_str = dt_vn.strftime("%Y-%m-%d")
        time_str = dt_vn.strftime("%H:%M")

        channel_name = channels.get(channel_id, f"Channel {channel_id}")

        matchup = clean_matchup(title)
        league = detect_league(title, desc)

        # Key để nhóm trận giống nhau (cùng ngày + giờ + tên trận)
        key = (date_str, time_str, matchup.lower())

        groups[key].append({
            "channel": channel_name,
            "league": league,
            "matchup": matchup,
            "date": date_str,
            "time": time_str,
        })

    # Xây dựng output JSON
    output = []
    for (date, time, _), items in groups.items():
        first = items[0]
        services = sorted({item["channel"] for item in items})   # loại trùng kênh

        output.append({
            "Date": date,
            "Time": time,
            "League": first["league"],
            "Matchup": first["matchup"],
            "Services": services
        })

    # Sắp xếp theo thời gian
    output.sort(key=lambda x: (x["Date"], x["Time"]))
    print(f"⚽ Tìm thấy {len(output)} trận Live")
    return output

def main():
    try:
        xml_content = download_xml(EPG_URL)
        channels = parse_channels(xml_content)
        matches = parse_programmes(xml_content, channels)

        # Lưu file JSON (đẹp, dễ đọc)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(matches, f, ensure_ascii=False, indent=2)

        print(f"✅ Hoàn thành! Đã lưu {len(matches)} trận vào {OUTPUT_FILE}")
        print(f"📂 File sẵn sàng commit vào GitHub repo")

    except Exception as e:
        print(f"❌ Lỗi: {e}")
        raise

if __name__ == "__main__":
    main()
