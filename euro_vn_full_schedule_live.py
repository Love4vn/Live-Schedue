"""
Tìm kênh phát sóng các trận đấu từ giải Ngoại hạng Anh, Bundesliga, Serie A, La Liga, Ligue 1,
tennis, F1, golf dựa trên ESPN API và EPG.
"""

import sys
import subprocess
import importlib.util

def install_and_import(package):
    try:
        spec = importlib.util.find_spec(package)
        if spec is None:
            print(f"Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    except Exception as e:
        print(f"Error installing {package}: {e}")
        sys.exit(1)

# Các module cần thiết
install_and_import('requests')
install_and_import('lxml')  # Tăng tốc XML parsing (tùy chọn)

import requests
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import xml.etree.ElementTree as ET
from urllib.parse import unquote
import gzip
from io import BytesIO
from datetime import datetime, timedelta

# ========== CẤU HÌNH ==========
EPG_SOURCES = [
    "https://hnlive.dramahay.xyz/epg.xml",
    "https://raw.githubusercontent.com/mrprince/epg/refs/heads/main/epg.xml.gz",
    "https://bit.ly/a1xepg",
    "https://raw.githubusercontent.com/karepech/Epgku/main/epg_wib_sports.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_DUMMY_CHANNELS.xml.gz"
]

LEAGUES = [
    {"name": "Premier League", "endpoint": "soccer/eng.1", "keywords": ["premier league", "epl"]},
    {"name": "Bundesliga", "endpoint": "soccer/ger.1", "keywords": ["bundesliga"]},
    {"name": "Serie A", "endpoint": "soccer/ita.1", "keywords": ["serie a"]},
    {"name": "La Liga", "endpoint": "soccer/esp.1", "keywords": ["laliga", "la liga"]},
    {"name": "Ligue 1", "endpoint": "soccer/fra.1", "keywords": ["ligue 1"]},
    {"name": "Tennis", "endpoint": "tennis/atp", "keywords": ["tennis", "atp", "wta"]},
    {"name": "F1", "endpoint": "racing/f1", "keywords": ["formula 1", "f1", "grand prix"]},
    {"name": "Golf", "endpoint": "golf/pga", "keywords": ["golf", "pga"]}
]

# Tạo mapping tên giải -> keywords
LEAGUES_BY_NAME = {league['name']: league for league in LEAGUES}

# ========== HÀM TIỆN ÍCH ==========
def safe_request(url, timeout=10):
    try:
        return requests.get(url, timeout=timeout)
    except:
        return None

def normalize_string(s):
    """Chuẩn hóa chuỗi để so sánh: lowercase, bỏ dấu, ký tự đặc biệt"""
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r'[^\w\s]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def time_diff_minutes(t1, t2):
    return abs((t1 - t2).total_seconds() / 60)

# ========== 1. LẤY LỊCH TỪ ESPN ==========
def fetch_espn_events(league):
    url = f"http://site.api.espn.com/apis/site/v2/sports/{league['endpoint']}/scoreboard"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            print(f"Lỗi ESPN {league['name']}: {resp.status_code}")
            return []
        data = resp.json()
        events = []
        for event in data.get('events', []):
            date_str = event.get('date')
            if not date_str:
                continue
            try:
                start_time = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            except:
                continue
            name = event.get('name', '')
            channels = set()
            competitions = event.get('competitions', [])
            for comp in competitions:
                for broadcast in comp.get('broadcasts', []):
                    for media in broadcast.get('media', []):
                        if 'name' in media:
                            channels.add(media['name'])
            events.append({
                'league': league['name'],
                'start': start_time,
                'name': name,
                'channels': list(channels)
            })
        return events
    except Exception as e:
        print(f"Lỗi xử lý ESPN {league['name']}: {e}")
        return []

def get_all_espn_events():
    all_events = []
    for league in LEAGUES:
        events = fetch_espn_events(league)
        all_events.extend(events)
        time.sleep(0.5)
    now = datetime.now()
    cutoff = now + timedelta(hours=24)
    filtered = [e for e in all_events if now <= e['start'] <= cutoff]
    return filtered

# ========== 2. LẤY EPG ==========
def fetch_epg_content(url):
    try:
        response = requests.get(url, timeout=15)
        if url.endswith('.gz'):
            with gzip.GzipFile(fileobj=BytesIO(response.content)) as f:
                return ET.parse(f)
        else:
            return ET.parse(BytesIO(response.content))
    except Exception as e:
        print(f"Lỗi tải EPG từ {url}: {str(e)}")
        return None

def parse_epg_channels(epg_url):
    channels = {}
    try:
        tree = fetch_epg_content(epg_url)
        if tree is None:
            return channels
        root = tree.getroot()
        for channel in root.findall('.//channel'):
            channel_id = channel.get('id')
            if not channel_id:
                continue
            display_names = []
            for dn in channel.findall('display-name'):
                if dn.text:
                    display_names.append(dn.text.strip())
            icon = channel.find('icon')
            icon_url = icon.get('src') if icon is not None else ''
            if display_names:
                channels[channel_id] = {
                    'names': display_names,
                    'icon': icon_url,
                    'source': epg_url
                }
    except Exception as e:
        print(f"Lỗi parse EPG channels từ {epg_url}: {str(e)}")
    return channels

def parse_epg_programmes(epg_url, start_time, end_time):
    programmes = []
    try:
        tree = fetch_epg_content(epg_url)
        if tree is None:
            return programmes
        root = tree.getroot()
        for programme in root.findall('.//programme'):
            start_str = programme.get('start', '')
            stop_str = programme.get('stop', '')
            channel_id = programme.get('channel', '')
            try:
                prog_start = datetime.strptime(start_str[:14], '%Y%m%d%H%M%S')
                prog_stop = datetime.strptime(stop_str[:14], '%Y%m%d%H%M%S')
                if prog_start <= end_time and prog_stop >= start_time:
                    title_elem = programme.find('title')
                    title = title_elem.text if title_elem is not None else ''
                    programmes.append({
                        'channel_id': channel_id,
                        'start': prog_start,
                        'stop': prog_stop,
                        'title': title
                    })
            except:
                continue
    except Exception as e:
        print(f"Lỗi parse EPG programmes từ {epg_url}: {str(e)}")
    return programmes

def collect_epg_data(epg_sources, start_time, end_time):
    all_channels = {}
    all_programmes = []
    for url in epg_sources:
        channels = parse_epg_channels(url)
        all_channels.update(channels)
        programmes = parse_epg_programmes(url, start_time, end_time)
        all_programmes.extend(programmes)
    return all_channels, all_programmes

# ========== 3. ĐỐI CHIẾU ESPN VỚI EPG ==========
def match_event_with_epg(event, epg_programmes, epg_channels, time_window=15):
    event_start = event['start']
    event_name_norm = normalize_string(event['name'])
    candidates = []
    for prog in epg_programmes:
        if time_diff_minutes(prog['start'], event_start) <= time_window:
            prog_title_norm = normalize_string(prog['title'])
            if (event_name_norm in prog_title_norm) or (prog_title_norm in event_name_norm):
                candidates.append(prog)
            elif any(keyword in prog_title_norm for keyword in LEAGUES_BY_NAME[event['league']]['keywords']):
                candidates.append(prog)
    if candidates:
        candidates.sort(key=lambda p: time_diff_minutes(p['start'], event_start))
        return candidates[0]['channel_id']
    return None

# ========== 4. TÌM KÊNH TỪ M3U ==========
def get_m3u_links():
    try:
        with open('M3U_list.txt', 'r') as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except FileNotFoundError:
        print("File M3U_list.txt không tồn tại. Tạo file trống để chạy thử.")
        return []

def parse_m3u(content):
    channels = []
    current_ch = {}
    extra_lines = []
    lines = content.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('#EXTINF'):
            if current_ch and 'name' in current_ch and 'url' in current_ch:
                if extra_lines:
                    current_ch['extra'] = extra_lines
                channels.append(current_ch)
            current_ch = {}
            extra_lines = []
            params = re.findall(r'([a-zA-Z-]+)="([^"]*)"', line)
            current_ch['params'] = {k.lower(): v for k, v in params}
            name_part = line.split(',', 1)
            if len(name_part) > 1:
                current_ch['name'] = unquote(name_part[1].strip())
            else:
                tvg_name = current_ch['params'].get('tvg-name', 'Unknown Channel')
                current_ch['name'] = unquote(tvg_name)
        elif line.startswith('http'):
            if current_ch and 'name' in current_ch:
                current_ch['url'] = line
                if extra_lines:
                    current_ch['extra'] = extra_lines
                channels.append(current_ch)
                current_ch = {}
                extra_lines = []
        elif line.startswith('#EXTVLCOPT') or line.startswith('#EXTGRP'):
            extra_lines.append(line)
    if current_ch and 'name' in current_ch and 'url' in current_ch:
        if extra_lines:
            current_ch['extra'] = extra_lines
        channels.append(current_ch)
    return channels

def match_channel_with_epg_id(channel_name, epg_id, epg_channels):
    norm_ch_name = normalize_string(channel_name)
    if epg_id in epg_channels:
        for name in epg_channels[epg_id]['names']:
            norm_epg_name = normalize_string(name)
            if norm_epg_name in norm_ch_name or norm_ch_name in norm_epg_name:
                return True
    norm_epg_id = normalize_string(epg_id)
    if norm_epg_id in norm_ch_name or norm_ch_name in norm_epg_id:
        return True
    return False

def check_channel_health(url, timeout=5):
    try:
        headers = {'User-Agent': 'VLC/3.0.18 LibVLC/3.0.18'}
        response = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        return response.status_code < 400
    except:
        return False

# ========== 5. MAIN ==========
def main():
    start_total = time.time()
    now = datetime.now()
    end_time = now + timedelta(hours=24)

    # 1. ESPN events
    print("📡 Lấy lịch từ ESPN...")
    espn_events = get_all_espn_events()
    print(f"Tìm thấy {len(espn_events)} sự kiện từ ESPN trong 24h tới.\n")

    if not espn_events:
        print("Không có sự kiện. Dừng.")
        return

    # 2. EPG data
    print("📺 Đang tải EPG...")
    epg_channels, epg_programmes = collect_epg_data(EPG_SOURCES, now - timedelta(hours=1), end_time + timedelta(hours=1))
    print(f"Thu thập {len(epg_channels)} kênh EPG và {len(epg_programmes)} chương trình.\n")

    # 3. Match events với EPG
    matched_events = []
    for event in espn_events:
        channel_id = match_event_with_epg(event, epg_programmes, epg_channels)
        if channel_id:
            matched_events.append({
                'event': event,
                'channel_id': channel_id,
                'channel_info': epg_channels.get(channel_id, {})
            })
            print(f"✅ {event['start'].strftime('%H:%M')} - {event['name']} -> {channel_id}")
        else:
            print(f"⚠️  {event['start'].strftime('%H:%M')} - {event['name']} (Không tìm thấy channel_id từ EPG)")

    if not matched_events:
        print("\nKhông có trận đấu nào khớp với EPG. Dừng.")
        return

    # 4. Lấy M3U links
    m3u_links = get_m3u_links()
    if not m3u_links:
        print("Không có M3U links.")
        return

    # 5. Parse M3U channels
    print("\n🔍 Đang tìm kênh từ M3U...")
    all_m3u_channels = []
    for url in m3u_links:
        try:
            resp = requests.get(url, timeout=10)
            channels = parse_m3u(resp.text)
            for ch in channels:
                if 'name' in ch and 'url' in ch:
                    res_match = re.search(r'(\d{3,4}[pP]|\d+K|HD|SD|FHD|UHD)', ch['name'])
                    ch['resolution'] = res_match.group(0).upper() if res_match else ''
                    all_m3u_channels.append(ch)
        except Exception as e:
            print(f"Lỗi xử lý {url}: {e}")

    print(f"Tổng số kênh từ M3U: {len(all_m3u_channels)}")

    # 6. Tìm kênh phù hợp cho từng event đã match
    results = []
    for item in matched_events:
        event = item['event']
        channel_id = item['channel_id']
        candidates = []
        for ch in all_m3u_channels:
            if match_channel_with_epg_id(ch['name'], channel_id, epg_channels):
                candidates.append(ch)
        if candidates:
            print(f"\n{event['start'].strftime('%H:%M')} - {event['name']}:")
            healthy = []
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_ch = {executor.submit(check_channel_health, ch['url']): ch for ch in candidates[:5]}
                for future in as_completed(future_to_ch):
                    ch = future_to_ch[future]
                    if future.result():
                        healthy.append(ch)
                        print(f"  ✅ {ch['name']} - {ch.get('resolution', 'N/A')}")
                    else:
                        print(f"  ❌ {ch['name']} - Không khả dụng")
            if healthy:
                best = healthy[0]  # Có thể chọn theo resolution cao hơn nếu muốn
                results.append({
                    'event': event,
                    'channel': best,
                    'channel_id': channel_id
                })
        else:
            print(f"\n{event['start'].strftime('%H:%M')} - {event['name']}: Không tìm thấy kênh nào khớp.")

    # 7. Xuất file M3U
    if results:
        with open('sports_channels.m3u', 'w', encoding='utf-8') as f:
            f.write('#EXTM3U\n')
            results.sort(key=lambda x: x['event']['start'])
            for item in results:
                event = item['event']
                ch = item['channel']
                match_time = event['start'].strftime('%H:%M %d/%m')
                title = f"{match_time} - {event['name']}"
                extinf = f'#EXTINF:-1 tvg-id="{item["channel_id"]}" group-title="{event["league"]}"'
                if ch.get('params', {}).get('tvg-logo'):
                    extinf += f' tvg-logo="{ch["params"]["tvg-logo"]}"'
                extinf += f',{title} - {ch["name"]}'
                f.write(extinf + '\n')
                if 'extra' in ch:
                    for extra in ch['extra']:
                        f.write(extra + '\n')
                f.write(ch['url'] + '\n')
        print(f"\n✅ Đã tạo file sports_channels.m3u với {len(results)} kênh.")
    else:
        print("\n❌ Không có kênh nào hoạt động.")

    print(f"\n⏱️  Tổng thời gian: {time.time() - start_total:.2f}s")

if __name__ == "__main__":
    main()
