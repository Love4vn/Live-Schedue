"""
EURO_VN_EPG_FINAL.py
================================
GIẢI PHÁP LẤY LỊCH TỪ EPG (XML) - CHUẨN XÁC & KHÔNG LO BỊ CHẶN
- Nguồn EPG: hnlive, mrprince, bit.ly, karepech, epgshare01
- Tính năng: Tự động giải nén .gz, lọc trận bóng đá LIVE, khớp kênh M3U
- Output: schedule.json (phân theo ngày) và live_schedule.m3u (phân theo giải)
"""

import json
import re
import urllib.request
import gzip
import time
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

# Từ khóa nhận diện bóng đá trực tiếp
FOOTBALL_KEYWORDS = ["vs", "premier league", "laliga", "serie a", "bundesliga", "ligue 1", "champions league", "europa league", "v-league", "ngoại hạng anh"]
LEAGUE_MAP = {
    "premier league": "Giải Ngoại Hạng Anh",
    "ngoại hạng anh": "Giải Ngoại Hạng Anh",
    "laliga": "Giải Tây Ban Nha",
    "serie a": "Giải Ý",
    "bundesliga": "Giải Đức",
    "ligue 1": "Giải Pháp",
    "champions league": "UEFA Champions League",
    "europa league": "UEFA Europa League",
    "conference league": "UEFA Conference League",
    "v-league": "V-League"
}

# ================== HELPER ==================
def fetch_epg(url):
    print(f"📥 Đang tải EPG: {url}")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=45) as r:
            content = r.read()
            if url.endswith(".gz") or content[:2] == b'\x1f\x8b':
                return gzip.decompress(content).decode("utf-8", errors="ignore")
            return content.decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"   ⚠️ Lỗi tải {url}: {e}")
        return None

def parse_epg_time(t_str):
    if not t_str: return None
    try:
        base = t_str.split()[0][:14]
        dt = datetime.strptime(base, "%Y%m%d%H%M%S")
        # Nếu có offset múi giờ trong chuỗi (ví dụ +0000)
        if " +0000" in t_str:
            dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TIMEZONE)
        else:
            dt = dt.replace(tzinfo=TIMEZONE)
        return dt
    except: return None

# ================== M3U PARSER ==================
def get_m3u_channels():
    """Phân tích file M3U_list.txt để lấy thông tin kênh, tvg-id, logo"""
    channels = []
    try:
        with open(M3U_LIST_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        
        segments = re.finditer(r'#EXTINF:(?P<info>.*?),(?P<name>.*?)\n(?P<url>http.*)', content, re.MULTILINE)
        for seg in segments:
            info = seg.group('info')
            name = seg.group('name').strip()
            url = seg.group('url').strip()
            
            tvg_id = re.search(r'tvg-id="([^"]*)"', info)
            tvg_logo = re.search(r'tvg-logo="([^"]*)"', info)
            
            channels.append({
                "name": name,
                "name_low": name.lower(),
                "tvg_id": tvg_id.group(1).lower() if tvg_id else "",
                "logo": tvg_logo.group(1) if tvg_logo else "",
                "url": url,
                "raw_info": info
            })
    except Exception as e:
        print(f"❌ Lỗi đọc M3U: {e}")
    return channels

# ================== MAIN ==================
def main():
    start_time = time.time()
    vn_now = datetime.now(TIMEZONE)
    print(f"🚀 Bắt đầu quét EPG [{vn_now.strftime('%H:%M:%S')}]")

    # 1. Nạp danh sách kênh M3U
    m3u_list = get_m3u_channels()
    print(f"✅ Đã nạp {len(m3u_list)} kênh từ {M3U_LIST_FILE}")

    found_matches = []
    processed_programs = set() # Tránh trùng lặp trận đấu trên cùng 1 kênh

    # 2. Quét lần lượt các nguồn EPG
    for url in EPG_SOURCES:
        xml_data = fetch_epg(url)
        if not xml_data: continue
        
        try:
            root = ET.fromstring(xml_data)
            
            # Tạo map ID kênh -> Display Name trong EPG
            epg_ch_map = {}
            for ch in root.findall('channel'):
                c_id = ch.get('id')
                d_name = ch.find('display-name').text if ch.find('display-name') is not None else ""
                if c_id: epg_ch_map[c_id.lower()] = d_name.lower()

            # Quét các chương trình
            for prog in root.findall('programme'):
                title = prog.find('title').text if prog.find('title') is not None else ""
                title_low = title.lower()
                
                # Điều kiện 1: Phải là bóng đá (có 'vs' hoặc tên giải)
                if any(kw in title_low for kw in FOOTBALL_KEYWORDS):
                    start_dt = parse_epg_time(prog.get('start'))
                    
                    # Điều kiện 2: Trận đấu sắp diễn ra hoặc đang diễn ra (trong 24h tới)
                    if start_dt and (vn_now - timedelta(hours=2)) <= start_dt <= (vn_now + timedelta(hours=24)):
                        ch_id = prog.get('channel', '').lower()
                        epg_ch_name = epg_ch_map.get(ch_id, "")
                        
                        # Điều kiện 3: Khớp kênh EPG với kênh M3U (theo ID hoặc Tên)
                        match_ch = None
                        for c in m3u_list:
                            if (ch_id and c['tvg_id'] == ch_id) or (epg_ch_name and epg_ch_name == c['name_low']):
                                match_ch = c
                                break
                        
                        if match_ch:
                            prog_key = f"{start_dt.strftime('%H%M')}_{match_ch['url']}"
                            if prog_key not in processed_programs:
                                # Xác định giải đấu để phân nhóm
                                group = "Lịch trực tiếp"
                                for kw, vn_name in LEAGUE_MAP.items():
                                    if kw in title_low:
                                        group = vn_name
                                        break
                                
                                found_matches.append({
                                    "time": start_dt.strftime("%I:%M %p"),
                                    "date_key": start_dt.strftime("%Y%m%d"),
                                    "date_display": start_dt.strftime("%A, %d/%m"),
                                    "datetime": start_dt,
                                    "match": title,
                                    "league": group,
                                    "channel_name": match_ch['name'],
                                    "url": match_ch['url'],
                                    "tvg_id": match_ch['tvg_id'],
                                    "logo": match_ch['logo']
                                })
                                processed_programs.add(prog_key)
        except Exception as e:
            print(f"   ⚠️ Lỗi Parse XML: {e}")

    # 3. Xuất file kết quả
    found_matches.sort(key=lambda x: x["datetime"])

    # Tạo schedule.json (theo mẫu đầu tiên: phân theo ngày)
    schedule_data = {"updated": vn_now.strftime("%Y-%m-%d %H:%M VN"), "days": {}}
    for m in found_matches:
        d_key = m["date_key"]
        if d_key not in schedule_data["days"]:
            schedule_data["days"][d_key] = {"date": m["date_display"], "games": []}
        
        schedule_data["days"][d_key]["games"].append({
            "league": m["league"],
            "time": m["time"],
            "match": m["match"],
            "source": m["channel_name"]
        })

    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(schedule_data, f, indent=2, ensure_ascii=False)

    # Tạo live_schedule.m3u (theo mẫu đầu tiên: phân theo giải)
    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for m in found_matches:
            extinf = f'#EXTINF:-1 tvg-id="{m["tvg_id"]}" tvg-logo="{m["logo"]}" group-title="{m["league"]}",{m["time"]} | {m["match"]} ({m["channel_name"]})'
            f.write(extinf + "\n")
            f.write(m["url"] + "\n")

    print(f"\n🎉 HOÀN THÀNH!")
    print(f"   • Tìm thấy: {len(found_matches)} trận đấu có link live.")
    print(f"   • Thời gian chạy: {time.time() - start_time:.1f}s")

if __name__ == "__main__":
    main()
