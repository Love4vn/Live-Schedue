#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import xml.etree.ElementTree as ET
import re
import sys
import json
from datetime import datetime, timedelta

# Danh sách từ khóa cần tìm (không phân biệt hoa/thường)
PATTERNS = [
    r'\bLive\b', r'\bTrực tiếp\b', r'\bTrực tiếp\b', r'\b直播\b', r'\b现场直播\b',
    r'\bLIVE\b', r'\b生放送\b', r'\b실시간\b', r'\bAo vivo\b', r'\bEn vivo\b',
    r'\bDirect\b', r'\bVivo\b', r'\bLive broadcast\b', r'\bLIVE NOW\b',
    r'\b🔴\b', r'\b⚽\b', r'\b🏀\b', r'\b🎾\b', r'\b🏐\b', r'\b🏈\b'
]

def parse_channels(xml_content):
    """Trả về dict mapping channel_id -> display-name"""
    root = ET.fromstring(xml_content)
    channels = {}
    for channel in root.findall('channel'):
        chan_id = channel.get('id')
        display_name = channel.findtext('display-name', default='')
        if chan_id:
            channels[chan_id] = display_name
    return channels

def parse_programmes(xml_content, channels):
    """Tìm các programme có chứa từ khóa live trong title hoặc desc"""
    root = ET.fromstring(xml_content)
    matches = []
    now = datetime.utcnow()
    today_str = now.strftime('%Y-%m-%d')

    for programme in root.findall('programme'):
        # Lấy dữ liệu an toàn, tránh None
        channel_id = programme.get('channel')
        start_str = programme.get('start', '')
        stop_str = programme.get('stop', '')
        title = programme.findtext('title', default='')
        desc = programme.findtext('desc', default='')
        icon_elem = programme.find('icon')
        icon = icon_elem.get('src', '') if icon_elem is not None else ''

        # Lấy tên kênh từ dict channels
        channel_name = channels.get(channel_id, channel_id)

        # Kiểm tra xem title hoặc desc có chứa từ khóa không
        matched = False
        for pattern in PATTERNS:
            if re.search(pattern, title, re.IGNORECASE) or re.search(pattern, desc, re.IGNORECASE):
                matched = True
                break

        if not matched:
            continue

        # Xử lý thời gian
        try:
            # Định dạng XMLTV: 20260417160000 +0000
            start_time = datetime.strptime(start_str[:14], '%Y%m%d%H%M%S')
            stop_time = datetime.strptime(stop_str[:14], '%Y%m%d%H%M%S')
        except Exception:
            continue

        # Chỉ lấy chương trình của ngày hôm nay (UTC)
        if start_time.strftime('%Y-%m-%d') != today_str:
            continue

        start_local = start_time + timedelta(hours=7)   # UTC+7
        stop_local = stop_time + timedelta(hours=7)

        # Rút gọn mô tả nếu quá dài
        short_desc = (desc[:200] + '...') if len(desc) > 200 else desc

        match = {
            'channel_id': channel_id,
            'channel_name': channel_name,
            'title': title,
            'desc': short_desc,
            'start_utc': start_time.strftime('%Y-%m-%d %H:%M UTC'),
            'start_local': start_local.strftime('%H:%M'),
            'stop_local': stop_local.strftime('%H:%M'),
            'duration_min': int((stop_time - start_time).total_seconds() // 60),
            'icon': icon
        }
        matches.append(match)

    # Sắp xếp theo giờ bắt đầu
    matches.sort(key=lambda x: x['start_utc'])
    return matches

def main():
    if len(sys.argv) < 2:
        print("Usage: python parse_epg.py <xml_file>")
        sys.exit(1)

    xml_file = sys.argv[1]
    with open(xml_file, 'r', encoding='utf-8') as f:
        xml_content = f.read()

    print("Đang tải EPG...")
    channels = parse_channels(xml_content)
    print("Đang phân tích channels...")
    print(f"Tìm thấy {len(channels)} kênh.")
    print("Đang phân tích programmes...")
    matches = parse_programmes(xml_content, channels)
    print(f"Tìm thấy {len(matches)} chương trình live hôm nay.")

    # In ra kết quả dạng JSON để GitHub Actions capture
    print(json.dumps(matches, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
