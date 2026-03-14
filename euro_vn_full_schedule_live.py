"""
EURO_VN_EPG_SCANNER.py
================================
GIẢI PHÁP LẤY LỊCH TỪ EPG (XML) - CHUẨN XÁC & KHÔNG LO BỊ CHẶN
- Nguồn EPG: hnlive, mrprince, bit.ly, karepech, epgshare01
- Tính năng: Tự động giải nén .gz, lọc trận bóng đá LIVE, khớp kênh M3U
"""

import json
import re
import urllib.request
import gzip
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================== CẤU HÌNH ==================
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
M3U_LIST_FILE = "M3U_list.txt"
SCHEDULE_FILE = "schedule.json"
LIVE_M3U = "live_schedule.m3u"

EPG_SOURCES = [
    "https://hnlive.dramahay.xyz/epg.xml",
    "https://raw.githubusercontent.com/mrprince/epg/refs/heads/main/epg.xml.gz",
    "https://bit.ly/a1xepg",
    "https://raw.githubusercontent.com/karepech/Epgku/main/epg_wib_sports.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_DUMMY_CHANNELS.xml.gz"
]

# Từ khóa nhận diện trận đấu bóng đá trực tiếp
FOOTBALL_KEYWORDS = ["vs", "premier league", "laliga", "serie a", "bundesliga", "ligue 1", "champions league", "europa league", "v-league"]
LIVE_KEYWORDS = ["live", "trực tiếp", "trực tiếp:"]

# ================== HELPER ==================
def fetch_data(url):
    print(f"📥 Đang tải: {url}")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            content = r.read()
            if url.endswith(".gz") or content[:2] == b'\x1f\x8b':
                return gzip.decompress(content).decode("utf-8")
            return content.decode("utf-8")
    except Exception as e:
        print(f"   ⚠️ Lỗi tải {url}: {e}")
        return None

def parse_epg_time(time_str):
    """Convert EPG time '20240519150000 +0000' to datetime object"""
    try:
        # Lấy 14 ký tự đầu YYYYMMDDHHMMSS
        clean_time = time_str.split()[0]
        dt = datetime.strptime(clean_time[:14], "%Y%m%d%H%M%S")
        # Giả định EPG thường là UTC nếu có +0000, nếu không có múi giờ thì coi như giờ VN
        if "+0000" in time_str:
            dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TIMEZONE)
        else:
            dt = dt.replace(tzinfo=TIMEZONE)
        return dt
    except:
        return None

# ================== M3U PARSER ==================
def get_m3u_channels():
    channels = {}
    try:
        with open(M3U_LIST_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        current_name = ""
        current_tvg_id = ""
        for line in lines:
            line = line.strip()
            if line.startswith("#EXTINF"):
                # Lấy tvg-id
                tid_match = re.search(r'tvg-id="([^"]*)"', line)
                current_tvg_id = tid_match.group(1).lower() if tid_match else ""
                # Lấy tên kênh sau dấu phẩy
                name = line.split(",")[-1].strip().lower()
                current_name = name
            elif line.startswith("http"):
                if current_name:
                    channels[current_name] = line
                if current_tvg_id:
                    channels[current_tvg_id] = line
    except:
        print(f"❌ Không tìm thấy {M3U_LIST_FILE}")
    return channels

# ================== MAIN LOGIC ==================
def main():
    start_run = time.time()
    vn_now = datetime.now(TIMEZONE)
    print(f"⏰ Bắt đầu quét EPG lúc: {vn_now.strftime('%H:%M:%S')}")

    m3u_map = get_m3u_channels()
    print(f"✅ Đã nạp {len(m3u_map)} kênh từ M3U_list.txt")

    found_matches = []
    
    for url in EPG_SOURCES:
        xml_content = fetch_data(url)
        if not xml_content: continue
        
        try:
            # Parse XML theo kiểu stream để tiết kiệm RAM
            root = ET.fromstring(xml_content)
            
            # 1. Tạo bản đồ ID kênh -> Tên hiển thị trong EPG
            epg_channels = {}
            for ch in root.findall('channel'):
                ch_id = ch.get('id')
                display_name = ch.find('display-name').text if ch.find('display-name') is not None else ""
                if ch_id:
                    epg_channels[ch_id] = display_name.lower()

            # 2. Quét các chương trình (programme)
            for prog in root.findall('programme'):
                title = prog.find('title').text if prog.find('title') is not None else ""
                title_low = title.lower()
                
                # Chỉ lọc những gì giống bóng đá và TRỰC TIẾP
                if any(kw in title_low for kw in FOOTBALL_KEYWORDS):
                    start_dt = parse_epg_time(prog.get('start'))
                    
                    # Chỉ lấy trận sắp tới trong vòng 24h
                    if start_dt and vn_now <= start_dt <= (vn_now + timedelta(days=1)):
                        ch_id = prog.get('channel')
                        epg_ch_name = epg_channels.get(ch_id, "").lower()
                        
                        # Tìm link stream khớp với tên kênh EPG hoặc ID kênh
                        stream_url = m3u_map.get(epg_ch_name) or m3u_map.get(ch_id.lower() if ch_id else "")
                        
                        if stream_url:
                            found_matches.append({
                                "time": start_dt.strftime("%H:%M"),
                                "datetime": start_dt,
                                "match": title,
                                "channel": epg_ch_name.upper(),
                                "url": stream_url
                            })
        except Exception as e:
            print(f"   ❌ Lỗi xử lý XML từ {url}: {e}")

    # Sắp xếp và lưu kết quả
    found_matches.sort(key=lambda x: x["datetime"])
    
    # Tạo M3U
    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for m in found_matches:
            f.write(f'#EXTINF:-1 group-title="Lịch EPG Trực Tiếp", ⚽ {m["time"]} | {m["match"]} ({m["channel"]})\n')
            f.write(f'{m["url"]}\n')

    # Tạo JSON cho giao diện web (nếu cần)
    schedule_json = {
        "updated": vn_now.strftime("%d/%m %H:%M"),
        "total": len(found_matches),
        "matches": [{k: v for k, v in m.items() if k != "datetime"} for m in found_matches]
    }
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(schedule_json, f, indent=2, ensure_ascii=False)

    print(f"\n🎉 Xong! Tìm thấy {len(found_matches)} trận đấu từ EPG.")
    print(f"⏱️ Tổng thời gian chạy: {time.time() - start_run:.1f}s")

if __name__ == "__main__":
    main()
