import json
import re
import urllib.request
import gzip
import time
import io
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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

FOOTBALL_KEYWORDS = ["vs", "premier league", "laliga", "serie a", "bundesliga", "ligue 1", "champions league", "v-league"]
LEAGUE_MAP = {"premier": "Ngoại hạng Anh", "laliga": "La Liga", "serie": "Serie A", "bundesliga": "Bundesliga", "ucl": "Champions League"}

# ================== BỘ ĐỌC M3U CẢI TIẾN ==================
def get_m3u_channels():
    channels = []
    try:
        with open(M3U_LIST_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        current_ch = {}
        for line in lines:
            line = line.strip()
            if line.startswith("#EXTINF"):
                # Lấy tvg-id
                tid = re.search(r'tvg-id="([^"]*)"', line, re.I)
                logo = re.search(r'tvg-logo="([^"]*)"', line, re.I)
                # Lấy tên kênh (phần sau dấu phẩy cuối cùng)
                name = line.split(",")[-1].strip()
                current_ch = {
                    "name": name.lower(),
                    "display": name,
                    "tvg_id": tid.group(1).lower() if tid else "",
                    "logo": logo.group(1) if logo else ""
                }
            elif line.startswith("http") and current_ch:
                current_ch["url"] = line
                channels.append(current_ch)
                current_ch = {}
    except Exception as e:
        print(f"❌ Lỗi file M3U: {e}")
    return channels

# ================== XỬ LÝ XML TIẾT KIỆM RAM ==================
def stream_epg(url, m3u_channels):
    print(f"📥 Đang xử lý: {url}")
    headers = {"User-Agent": "Mozilla/5.0"}
    found = []
    vn_now = datetime.now(TIMEZONE)
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as response:
            content = response.read()
            if url.endswith(".gz") or content[:2] == b'\x1f\x8b':
                content = gzip.decompress(content)
            
            # Dùng iterparse để không bị Out Of Memory
            context = ET.iterparse(io.BytesIO(content), events=('start', 'end'))
            epg_ch_map = {}
            
            for event, elem in context:
                if event == 'end' and elem.tag == 'channel':
                    c_id = elem.get('id')
                    d_name = elem.findtext('display-name')
                    if c_id: epg_ch_map[c_id.lower()] = (d_name or "").lower()
                    elem.clear() # Giải phóng bộ nhớ
                
                elif event == 'end' and elem.tag == 'programme':
                    title = (elem.findtext('title') or "").lower()
                    if any(k in title for k in FOOTBALL_KEYWORDS):
                        start_raw = elem.get('start')
                        # Convert time
                        try:
                            t_str = start_raw.split()[0][:14]
                            dt = datetime.strptime(t_str, "%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo("UTC")).astimezone(TIMEZONE)
                            
                            if vn_now <= dt <= (vn_now + timedelta(hours=24)):
                                ch_id = (elem.get('channel') or "").lower()
                                ch_name_epg = epg_ch_map.get(ch_id, "")
                                
                                # So khớp với M3U
                                for m_ch in m3u_channels:
                                    if (ch_id and m_ch['tvg_id'] == ch_id) or (ch_name_epg and m_ch['name'] == ch_name_epg):
                                        found.append({
                                            "time": dt.strftime("%H:%M"),
                                            "datetime": dt,
                                            "match": elem.findtext('title'),
                                            "channel": m_ch['display'],
                                            "url": m_ch['url'],
                                            "logo": m_ch['logo'],
                                            "tvg_id": m_ch['tvg_id']
                                        })
                                        break
                        except: pass
                    elem.clear() # Quan trọng: Xóa tag đã xử lý để giải phóng RAM
            del content
    except Exception as e:
        print(f"   ⚠️ Lỗi: {e}")
    return found

def main():
    start_t = time.time()
    m3u_channels = get_m3u_channels()
    print(f"✅ Đã nạp {len(m3u_channels)} kênh từ M3U_list.txt")
    
    if not m3u_channels:
        print("❌ Cảnh báo: Không có kênh nào trong file M3U. Hãy kiểm tra định dạng file!")
        return

    all_matches = []
    for url in EPG_SOURCES:
        all_matches.extend(stream_epg(url, m3u_channels))

    # Loại bỏ trùng lặp (nếu cùng 1 trận trên cùng 1 kênh từ nhiều nguồn EPG)
    unique_matches = {}
    for m in all_matches:
        key = f"{m['time']}_{m['channel']}"
        unique_matches[key] = m
    
    final_list = sorted(unique_matches.values(), key=lambda x: x['datetime'])

    # Ghi file M3U
    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for m in final_list:
            f.write(f'#EXTINF:-1 tvg-id="{m["tvg_id"]}" tvg-logo="{m["logo"]}" group-title="EPG LIVE", ⚽ {m["time"]} | {m["match"]} ({m["channel"]})\n')
            f.write(f"{m['url']}\n")

    # Ghi file JSON
    output = {"updated": datetime.now(TIMEZONE).strftime("%d/%m %H:%M"), "total": len(final_list), "matches": []}
    for m in final_list:
        output["matches"].append({"time": m["time"], "match": m["match"], "source": m["channel"]})
    
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"🎉 Xong! Tìm thấy {len(final_list)} trận. Thời gian: {time.time()-start_t:.1f}s")

if __name__ == "__main__":
    main()
