"""
EURO_VN_LIVE_TODAY.py
- Chỉ lấy lịch TRỰC TIẾP hôm nay (Vietnam Time)
- Nguồn: FotMob (Ưu tiên) + ESPN (Dự phòng)
- Tự động bỏ qua lỗi 404
"""

import json
import urllib.request
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ================== CẤU HÌNH ==================
DAYS_AHEAD = 1  # Chỉ lấy hôm nay
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
M3U_LIST_FILE = "M3U_list.txt"
SCHEDULE_FILE = "schedule.json"
LIVE_M3U = "live_schedule.m3u"

# Danh sách giải đấu quan trọng
LEAGUES = {
    "47": "Ngoại hạng Anh",
    "54": "Bundesliga",
    "55": "Serie A",
    "87": "La Liga",
    "53": "Ligue 1",
    "42": "Champions League",
    "73": "Europa League",
    "9002": "Conference League"
}

def get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.fotmob.com",
        "Referer": "https://www.fotmob.com/"
    }

def fetch_fotmob(date_str):
    """Lấy dữ liệu từ FotMob API (Dùng subdomain 'pub' để tránh 404)"""
    url = f"https://pub.fotmob.com/api/matches?date={date_str}&timezone=Asia/Ho_Chi_Minh"
    try:
        req = urllib.request.Request(url, headers=get_headers())
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"   ⚠️ Lỗi FotMob ({e}), đang chuyển sang nguồn dự phòng...")
        return None

def fetch_espn():
    """Nguồn dự phòng từ ESPN nếu FotMob chặn"""
    url = "https://site.api.espn.com/apis/site/v2/sports/football/scorepanel"
    try:
        req = urllib.request.Request(url, headers=get_headers())
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except:
        return None

def main():
    print(f"🚀 Đang cập nhật lịch trực tiếp cho ngày: {datetime.now(TIMEZONE).strftime('%d/%m/%Y')}")
    
    today = datetime.now(TIMEZONE).strftime("%Y%m%d")
    data = fetch_fotmob(today)
    
    matches_found = []
    
    if data and "leagues" in data:
        # Xử lý dữ liệu FotMob
        for lg in data["leagues"]:
            lg_id = str(lg.get("id"))
            if lg_id in LEAGUES:
                for m in lg.get("matches", []):
                    # Lấy thông tin kênh (nếu có)
                    channels = []
                    if "broadcasters" in m and m["broadcasters"]:
                        # Ưu tiên kênh quốc tế nổi tiếng
                        channels = [b.get("name") for b in m["broadcasters"].get("national", [])]
                    
                    if not channels: channels = ["Xem Trực Tiếp"]
                    
                    matches_found.append({
                        "time": m.get("time"),
                        "name": f"{m.get('home', {}).get('name')} vs {m.get('away', {}).get('name')}",
                        "league": LEAGUES[lg_id],
                        "channels": channels
                    })
    else:
        # Nếu FotMob lỗi, dùng ESPN (thường không có 404)
        print("   🔄 Đang lấy dữ liệu từ ESPN...")
        espn_data = fetch_espn()
        if espn_data and "scores" in espn_data:
            for s in espn_data["scores"]:
                lg_name = s.get("leagues", [{}])[0].get("name", "Bóng đá")
                for ev in s.get("events", []):
                    channels = [ant.get("type", {}).get("detail", "LIVE") for ant in ev.get("competitions", [{}])[0].get("airings", [])]
                    if not channels: channels = ["Kênh Trực Tiếp"]
                    
                    matches_found.append({
                        "time": ev.get("date"),
                        "name": ev.get("name"),
                        "league": lg_name,
                        "channels": channels
                    })

    if not matches_found:
        print("❌ Rất tiếc, hiện tại không tìm thấy trận đấu nào đang hoặc sắp diễn ra.")
        return

    # Xuất file M3U (Giả lập link hoặc gán tên trận)
    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for m in matches_found:
            for ch in m["channels"]:
                f.write(f'#EXTINF:-1 group-title="{m["league"]}", ⚽ {m["name"]} ({ch})\n')
                # Ở đây bạn có thể thay bằng link IPTV thật của bạn nếu có M3U_list.txt
                f.write(f"http://example.com/live?match={m['name'].replace(' ', '_')}\n")

    print(f"✅ Đã tìm thấy {len(matches_found)} trận đấu. File '{LIVE_M3U}' đã sẵn sàng!")

if __name__ == "__main__":
    main()
