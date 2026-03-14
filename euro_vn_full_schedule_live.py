import requests
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse
import gzip
from io import BytesIO
from datetime import datetime, timedelta
import json

def get_m3u_links():
    with open('M3U_list.txt', 'r') as f:
        return [line.strip() for line in f.readlines() if line.strip()]

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

def fetch_epg_content(url):
    """Tải nội dung EPG từ URL (hỗ trợ cả .xml và .xml.gz)"""
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
    """Lấy danh sách channels từ EPG"""
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
                
            # Lấy tất cả display-name
            display_names = []
            for dn in channel.findall('display-name'):
                if dn.text:
                    display_names.append(dn.text.strip())
            
            # Lấy icon nếu có
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

def parse_epg_programmes(epg_url, date=None):
    """Lấy chương trình từ EPG cho một ngày cụ thể"""
    programmes = []
    try:
        tree = fetch_epg_content(epg_url)
        if tree is None:
            return programmes
            
        root = tree.getroot()
        
        # Nếu không chỉ định ngày, lấy chương trình của ngày hiện tại và ngày mai
        if date is None:
            today = datetime.now().date()
            tomorrow = today + timedelta(days=1)
            dates_to_check = [today, tomorrow]
        else:
            dates_to_check = [date]
        
        for programme in root.findall('.//programme'):
            start_str = programme.get('start', '')
            channel_id = programme.get('channel', '')
            
            # Parse thời gian bắt đầu
            try:
                # Format: 20240314120000 +0000
                start_time = datetime.strptime(start_str[:14], '%Y%m%d%H%M%S')
                start_date = start_time.date()
                
                # Chỉ lấy chương trình trong các ngày cần kiểm tra
                if start_date in dates_to_check:
                    title_elem = programme.find('title')
                    title = title_elem.text if title_elem is not None else ''
                    
                    # Lọc các chương trình thể thao
                    if is_sports_programme(programme, title):
                        programmes.append({
                            'channel_id': channel_id,
                            'start': start_time,
                            'title': title,
                            'raw_data': programme
                        })
            except:
                continue
                
    except Exception as e:
        print(f"Lỗi parse EPG programmes từ {epg_url}: {str(e)}")
    
    return programmes

def is_sports_programme(programme_elem, title):
    """Kiểm tra xem chương trình có phải thể thao không"""
    title_lower = title.lower()
    
    # Từ khóa thể thao
    sports_keywords = [
        'football', 'soccer', 'basketball', 'tennis', 'golf', 'rugby',
        'f1', 'formula 1', 'motogp', 'boxing', 'ufc', 'mma',
        'premier league', 'la liga', 'bundesliga', 'serie a', 'ligue 1',
        'champions league', 'europa league', 'world cup', 'euro',
        'bóng đá', 'thể thao', 'tennis', 'cầu lông', 'bơi lội',
        'olympic', 'asian games', 'sea games', 'aff cup',
        'nba', 'nfl', 'nhl', 'mlb', 'uefa', 'fifa'
    ]
    
    # Kiểm tra category nếu có
    category = programme_elem.find('category')
    if category is not None and category.text:
        cat_lower = category.text.lower()
        if any(keyword in cat_lower for keyword in sports_keywords):
            return True
    
    # Kiểm tra title
    return any(keyword in title_lower for keyword in sports_keywords)

def normalize_channel_name(name):
    """Chuẩn hóa tên kênh để so khớp"""
    # Loại bỏ dấu, ký tự đặc biệt và chuyển về lower
    name = name.lower()
    # Loại bỏ độ phân giải (1080p, 4K, HD, ...)
    name = re.sub(r'\b(1080|720|480|4k|uhd|fhd|hd|sd)[p\s]*', '', name)
    # Loại bỏ ký tự đặc biệt
    name = re.sub(r'[^\w\s]', '', name)
    # Loại bỏ khoảng trắng thừa
    name = ' '.join(name.split())
    return name

def match_channel_with_epg(channel_name, epg_channels):
    """So khớp tên kênh với danh sách channel từ EPG"""
    normalized_channel = normalize_channel_name(channel_name)
    
    best_match = None
    best_score = 0
    
    for epg_id, epg_data in epg_channels.items():
        for epg_name in epg_data['names']:
            normalized_epg = normalize_channel_name(epg_name)
            
            # Tính điểm match
            score = 0
            
            # Nếu tên channel chứa epg name hoặc ngược lại
            if normalized_epg in normalized_channel:
                score = len(normalized_epg) / len(normalized_channel)
            elif normalized_channel in normalized_epg:
                score = len(normalized_channel) / len(normalized_epg)
            
            # Tăng điểm nếu có keyword đặc biệt
            sports_keywords = ['sport', 'football', 'espn', 'fox', 'tnt', 'sky']
            for keyword in sports_keywords:
                if keyword in normalized_channel and keyword in normalized_epg:
                    score += 0.3
            
            if score > best_score and score > 0.5:  # Ngưỡng match tối thiểu 50%
                best_score = score
                best_match = {
                    'epg_id': epg_id,
                    'epg_name': epg_name,
                    'match_score': score,
                    'icon': epg_data.get('icon', '')
                }
    
    return best_match

def get_upcoming_matches(epg_sources, hours_ahead=24):
    """Lấy các trận đấu sắp tới từ tất cả EPG sources"""
    all_programmes = []
    all_channels = {}
    
    # Thu thập tất cả channels từ EPG
    for url in epg_sources:
        channels = parse_epg_channels(url)
        all_channels.update(channels)
        
        # Lấy programmes
        programmes = parse_epg_programmes(url)
        all_programmes.extend(programmes)
    
    # Lọc các trận đấu trong khoảng thời gian
    now = datetime.now()
    cutoff_time = now + timedelta(hours=hours_ahead)
    
    upcoming_matches = []
    for prog in all_programmes:
        if now <= prog['start'] <= cutoff_time:
            # Thêm thông tin channel từ EPG
            channel_info = all_channels.get(prog['channel_id'], {})
            prog['channel_info'] = channel_info
            upcoming_matches.append(prog)
    
    # Sắp xếp theo thời gian
    upcoming_matches.sort(key=lambda x: x['start'])
    
    return upcoming_matches, all_channels

def main():
    start_time = time.time()
    
    # 1. Danh sách EPG sources
    epg_sources = [
        "https://hnlive.dramahay.xyz/epg.xml",
        "https://raw.githubusercontent.com/mrprince/epg/refs/heads/main/epg.xml.gz",
        "https://bit.ly/a1xepg",
        "https://raw.githubusercontent.com/karepech/Epgku/main/epg_wib_sports.xml",
        "https://epgshare01.online/epgshare01/epg_ripper_DUMMY_CHANNELS.xml.gz"
    ]
    
    # 2. Lấy các trận đấu sắp tới
    print("Đang lấy lịch thi đấu từ EPG...")
    upcoming_matches, epg_channels = get_upcoming_matches(epg_sources, hours_ahead=24)
    
    if not upcoming_matches:
        print("Không tìm thấy trận đấu nào trong 24h tới!")
        return
    
    print(f"Tìm thấy {len(upcoming_matches)} trận đấu trong 24h tới")
    
    # 3. Lấy danh sách M3U links
    m3u_links = get_m3u_links()
    
    # 4. Thu thập tất cả channels từ M3U
    print("Đang thu thập kênh từ M3U links...")
    all_channels = []
    
    for url in m3u_links:
        try:
            response = requests.get(url, timeout=10)
            channels = parse_m3u(response.text)
            
            for ch in channels:
                if 'name' in ch and 'url' in ch:
                    # Thử match với EPG
                    match_result = match_channel_with_epg(ch['name'], epg_channels)
                    if match_result:
                        ch['epg_match'] = match_result
                    
                    # Phát hiện độ phân giải
                    res_match = re.search(r'(\d{3,4}[pP]|\d+K|HD|SD|FHD|UHD)', ch['name'].lower())
                    ch['resolution'] = res_match.group(0).upper() if res_match else ""
                    
                    all_channels.append(ch)
                    
        except Exception as e:
            print(f"Lỗi xử lý {url}: {str(e)}")
    
    print(f"Thu thập được {len(all_channels)} kênh")
    
    # 5. Tìm kênh phù hợp cho từng trận đấu
    print("\n" + "="*80)
    print("KẾT QUẢ TÌM KÊNH CHO CÁC TRẬN ĐẤU SẮP TỚI")
    print("="*80)
    
    matches_with_channels = []
    
    for match in upcoming_matches:
        match_time = match['start'].strftime('%H:%M %d/%m/%Y')
        match_title = match['title']
        channel_id = match['channel_id']
        
        print(f"\n📺 {match_time} - {match_title}")
        print(f"   Channel ID từ EPG: {channel_id}")
        
        # Tìm kênh phù hợp từ danh sách M3U
        suitable_channels = []
        
        for ch in all_channels:
            # Nếu channel đã được match với EPG
            if 'epg_match' in ch and ch['epg_match']['epg_id'] == channel_id:
                suitable_channels.append(ch)
            # Hoặc tên kênh chứa channel_id hoặc ngược lại
            elif channel_id.lower() in ch['name'].lower() or ch['name'].lower() in channel_id.lower():
                suitable_channels.append(ch)
        
        if suitable_channels:
            print(f"   🔍 Tìm thấy {len(suitable_channels)} kênh phù hợp:")
            
            # Kiểm tra health các kênh
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_ch = {executor.submit(check_channel_health, ch['url']): ch for ch in suitable_channels[:5]}
                
                for future in as_completed(future_to_ch):
                    ch = future_to_ch[future]
                    if future.result():
                        print(f"   ✅ {ch['name']} - {ch.get('resolution', 'N/A')}")
                        matches_with_channels.append({
                            'match': match,
                            'channel': ch
                        })
                    else:
                        print(f"   ❌ {ch['name']} - Không khả dụng")
        else:
            print("   ❌ Không tìm thấy kênh phù hợp")
    
    # 6. Tạo M3U file với các kênh phù hợp
    if matches_with_channels:
        print("\n" + "="*80)
        print("ĐANG TẠO FILE M3U VỚI CÁC KÊNH PHÙ HỢP...")
        
        with open('sports_channels.m3u', 'w', encoding='utf-8') as f:
            f.write('#EXTM3U\n')
            
            # Nhóm theo thời gian
            matches_with_channels.sort(key=lambda x: x['match']['start'])
            
            for item in matches_with_channels:
                match = item['match']
                ch = item['channel']
                
                match_time = match['start'].strftime('%H:%M %d/%m')
                title = f"{match_time} - {match['title']}"
                
                # Tạo EXTINF line
                extinf = f'#EXTINF:-1 tvg-id="{ch.get("epg_match", {}).get("epg_id", "")}"'
                extinf += f' group-title="Trận đấu sắp tới"'
                if ch.get('epg_match', {}).get('icon'):
                    extinf += f' tvg-logo="{ch["epg_match"]["icon"]}"'
                extinf += f',{title} - {ch["name"]}'
                
                f.write(extinf + '\n')
                
                # Ghi extra lines nếu có
                if 'extra' in ch:
                    for extra_line in ch['extra']:
                        f.write(f"{extra_line}\n")
                
                f.write(f"{ch['url']}\n")
        
        print(f"✅ Đã tạo file sports_channels.m3u với {len(matches_with_channels)} kênh")
    
    # Thống kê
    total_time = time.time() - start_time
    print(f"\n⏱️  Thời gian xử lý: {total_time:.2f}s")

def check_channel_health(url, timeout=5):
    """Kiểm tra kênh có hoạt động không"""
    try:
        headers = {'User-Agent': 'VLC/3.0.18 LibVLC/3.0.18'}
        response = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        return response.status_code < 400
    except:
        return False

if __name__ == "__main__":
    main()
