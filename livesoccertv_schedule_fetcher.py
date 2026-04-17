"""
livesoccertv_schedule_fetcher.py
================================
Lấy lịch trực tiếp từ livesoccertv.com (không match kênh M3U)
Xuất ra livesoccertv_schedule.json
"""

import asyncio
import json
import re
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional

import aiohttp
from bs4 import BeautifulSoup

# ================== CẤU HÌNH ==================
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
SOFASCORE_CACHE_FILE = "sofascore_cache.json"  # không dùng nhưng giữ để tránh lỗi

# ================== HELPER FUNCTIONS ==================
def vn_time(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC")).astimezone(TIMEZONE)
    return dt.strftime("%d/%m %I:%M %p")

def normalize(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return " ".join(c for c in s if unicodedata.category(c) != "Mn")

def parse_time_from_string(time_str: str, date_str: str) -> Optional[int]:
    """
    Chuyển đổi chuỗi thời gian (ví dụ '7:30', '15:00') cùng với ngày (YYYY-MM-DD)
    thành timestamp UTC.
    """
    try:
        # Xử l� các định dạng như '7:30', '10:00', '15:30'
        time_str = time_str.strip()
        if ':' not in time_str:
            return None
        hour, minute = map(int, time_str.split(':'))
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        dt = dt.replace(hour=hour, minute=minute, second=0, tzinfo=TIMEZONE)
        # Chuyển về UTC timestamp
        return int(dt.astimezone(ZoneInfo("UTC")).timestamp())
    except:
        return None

def extract_country_and_channel(img_tag) -> tuple:
    """Từ thẻ img của kênh, lấy tên quốc gia và tên kênh."""
    alt = img_tag.get('alt', '')
    title = img_tag.get('title', '')
    # Nếu có title thì ưu tiên, không thì dùng alt
    channel_name = title or alt
    # Tìm quốc gia: thường có dạng flag <country> hoặc trong class
    country = "unknown"
    for cls in img_tag.get('class', []):
        if cls.startswith('flag-'):
            country = cls.replace('flag-', '').replace('-', ' ')
            break
    # Nếu không, thử lấy từ alt
    if country == "unknown" and alt:
        # alt thường là tên kênh, không phải quốc gia
        pass
    return country.strip(), channel_name.strip()

async def fetch_livesoccertv_schedule(start_ts: int, max_ts: int) -> List[Dict]:
    """
    Crawl livesoccertv.com/schedules cho các ngày trong khoảng thời gian.
    Trả về danh sách các trận đấu với cấu trúc:
    {
        "league": "Premier League",
        "match": "Arsenal vs Chelsea",
        "kick_utc": 1234567890,
        "time": "18/04 07:30 PM",
        "tv_channels": [{"country": "uk", "channels": ["Sky Sports"]}, ...]
    }
    """
    all_games = []
    # Tạo danh sách các ngày cần crawl (từ start_ts đến max_ts)
    start_date = datetime.fromtimestamp(start_ts, tz=ZoneInfo("UTC")).date()
    end_date = datetime.fromtimestamp(max_ts, tz=ZoneInfo("UTC")).date()
    current_date = start_date
    date_list = []
    while current_date <= end_date:
        date_list.append(current_date.strftime("%Y-%m-%d"))
        current_date += timedelta(days=1)

    async with aiohttp.ClientSession() as session:
        for date_str in date_list:
            url = f"https://www.livesoccertv.com/schedules/{date_str}/"
            print(f"📡 Đang crawl: {url}")
            try:
                async with session.get(url, timeout=15) as resp:
                    if resp.status != 200:
                        print(f"   ⚠️ Không thể truy cập {date_str} (HTTP {resp.status})")
                        continue
                    html = await resp.text()
            except Exception as e:
                print(f"   ❌ Lỗi khi tải {date_str}: {e}")
                continue

            soup = BeautifulSoup(html, 'html.parser')
            # Tìm tất cả các hàng trận đấu (thường có class 'matchrow' hoặc id dạng số)
            match_rows = soup.find_all('tr', class_='matchrow')
            if not match_rows:
                # fallback: tìm theo id bắt đầu bằng số
                match_rows = soup.find_all('tr', id=re.compile(r'^\d+$'))

            for row in match_rows:
                try:
                    # ---- Thời gian ----
                    time_cell = row.find('td', class_='timecol')
                    if not time_cell:
                        time_cell = row.find('td', class_='timecell')
                    if not time_cell:
                        continue
                    time_text = time_cell.get_text(strip=True)
                    # Thời gian có thể ở dạng "7:30" hoặc "15:00"
                    # Loại bỏ các ký tự không phải số và dấu hai chấm
                    time_match = re.search(r'\d{1,2}:\d{2}', time_text)
                    if not time_match:
                        continue
                    time_str = time_match.group()
                    kick_utc = parse_time_from_string(time_str, date_str)
                    if not kick_utc or not (start_ts <= kick_utc <= max_ts):
                        continue

                    # ---- Tên trận đấu ----
                    match_cell = row.find('td', id='match')
                    if not match_cell:
                        match_cell = row.find('td', class_='matchcell')
                    if not match_cell:
                        continue
                    match_link = match_cell.find('a')
                    if not match_link:
                        continue
                    match_name = match_link.get_text(strip=True)
                    # Chuẩn hóa tên trận (thay @ bằng vs)
                    match_name = match_name.replace(' @ ', ' vs ')

                    # ---- Giải đấu ----
                    league_cell = row.find('td', class_='compcell_right')
                    if not league_cell:
                        league_cell = row.find('td', class_='compcell')
                    league = league_cell.get_text(strip=True) if league_cell else "Unknown"

                    # ---- Kênh phát sóng ----
                    # Tìm cột chứa kênh (thường class 'channelcol' hoặc 'channels')
                    channel_cell = row.find('td', class_='channelcol')
                    if not channel_cell:
                        channel_cell = row.find('td', class_='channels')
                    if not channel_cell:
                        # Một số trang không có cột kênh riêng -> bỏ qua
                        continue

                    # Lấy tất cả các ảnh cờ (flag) đại diện cho kênh
                    channel_imgs = channel_cell.find_all('img', class_=re.compile(r'flag'))
                    if not channel_imgs:
                        # Fallback: tìm các thẻ a chứa tên kênh
                        channel_links = channel_cell.find_all('a')
                        # Gom nhóm theo quốc gia (nếu có)
                        pass

                    # Gom kênh theo quốc gia
                    channels_by_country = {}
                    for img in channel_imgs:
                        country, channel = extract_country_and_channel(img)
                        if not channel:
                            continue
                        if country not in channels_by_country:
                            channels_by_country[country] = set()
                        channels_by_country[country].add(channel)

                    # Nếu không tìm thấy kênh qua ảnh, thử qua thẻ a
                    if not channels_by_country:
                        for a in channel_cell.find_all('a', href=True):
                            channel_name = a.get_text(strip=True)
                            if channel_name:
                                # Không rõ quốc gia -> gom chung vào 'unknown'
                                channels_by_country.setdefault('unknown', set()).add(channel_name)

                    if not channels_by_country:
                        continue  # không có kênh thì bỏ qua trận này

                    tv_channels = []
                    for country, ch_set in channels_by_country.items():
                        tv_channels.append({
                            "country": country,
                            "channels": sorted(list(ch_set))
                        })

                    # Tạo đối tượng game
                    game = {
                        "league": league,
                        "match": match_name,
                        "kick_utc": kick_utc,
                        "time": vn_time(kick_utc),
                        "tv_channels": tv_channels,
                        "source": "livesoccertv"
                    }
                    all_games.append(game)

                except Exception as e:
                    print(f"   ⚠️ Lỗi xử lý một hàng: {e}")
                    continue

            # Tránh request quá nhanh
            await asyncio.sleep(1)

    return all_games

# ================== MAIN ==================
async def main():
    vn_now = datetime.now(TIMEZONE)
    start_ts = int(datetime.now(TIMEZONE).timestamp()) - 7200   # 2 giờ trước
    max_ts = int(datetime.now(TIMEZONE).timestamp()) + 86400     # 24 giờ tới

    print("🔄 Bắt đầu lấy lịch từ livesoccertv.com...")
    print(f"   Khoảng thời gian: {vn_time(start_ts)} -> {vn_time(max_ts)}")

    games = await fetch_livesoccertv_schedule(start_ts, max_ts)

    # Loại bỏ trùng lặp (dựa trên match + kick_utc)
    seen = set()
    unique_games = []
    for g in games:
        key = (g['kick_utc'], normalize(g['match']))
        if key not in seen:
            seen.add(key)
            unique_games.append(g)
    games = unique_games

    # Sắp xếp theo thời gian
    games.sort(key=lambda x: x['kick_utc'])

    # Lưu kết quả
    output = {
        "updated": vn_now.strftime("%Y-%m-%d %H:%M VN"),
        "total_matches": len(games),
        "matches": games
    }
    with open("livesoccertv_schedule.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Đã lưu {len(games)} trận vào livesoccertv_schedule.json")

if __name__ == "__main__":
    asyncio.run(main())
