# wheresthematch.py
import asyncio
import re
from datetime import datetime
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

# Danh sách kênh UK phổ biến (dùng để lọc, không bắt buộc)
UK_CHANNELS = [
    "Sky Sports Main Event", "Sky Sports Premier League", "Sky Sports Football",
    "Sky Sports Arena", "Sky Sports Action", "Sky Sports Mix", "Sky Sports News",
    "Sky Sports+", "Sky Sports", "TNT Sports 1", "TNT Sports 2", "TNT Sports 3",
    "TNT Sports 4", "TNT Sports Ultimate", "TNT Sports Extra", "TNT Sports",
    "BBC One", "BBC Two", "BBC iPlayer", "ITV1", "ITV4", "ITVX", "Channel 4",
    "Amazon Prime Video", "Amazon Prime", "Premier Sports 1", "Premier Sports 2",
    "Premier Sports", "BT Sport 1", "BT Sport 2", "BT Sport 3", "LaLigaTV",
    "FreeSports", "discovery+", "Discovery+", "DAZN"
]

async def fetch_wtm_fixtures() -> List[Dict[str, Any]]:
    """
    Lấy danh sách trận đấu từ Where's The Match (https://www.wheresthematch.com/live-football-on-tv/)
    Trả về list các dict chứa: home, away, kickoff_utc (timestamp), competition, channels
    """
    url = "https://www.wheresthematch.com/live-football-on-tv/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        async with AsyncSession() as session:
            resp = await session.get(url, impersonate="chrome120", headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"[WTM] HTTP {resp.status_code}")
                return []
            html = resp.text
    except Exception as e:
        print(f"[WTM] Request failed: {e}")
        return []

    # Parse HTML trong thread riêng để không block event loop
    loop = asyncio.get_event_loop()
    fixtures = await loop.run_in_executor(None, _parse_wtm_html, html)
    return fixtures

def _parse_wtm_html(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, 'lxml')
    rows = soup.select('tr[itemscope][itemtype*="BroadcastEvent"]')
    fixtures = []

    for row in rows:
        # Bỏ qua các trận nữ
        if re.search(r"women'?s|womens|ladies", row.get_text(), re.I):
            continue

        # ---- Đội nhà / đội khách ----
        team_links = row.select('td.fixture-details a[title]')
        home = away = None
        if len(team_links) >= 2:
            home = team_links[0].get('title') or team_links[0].text.strip()
            away = team_links[-1].get('title') or team_links[-1].text.strip()
        else:
            # fallback: parse text "Team A v Team B"
            fixture_cell = row.select_one('td.fixture-details')
            if fixture_cell:
                text = fixture_cell.get_text(strip=True)
                m = re.search(r'(.+?)\s+(?:v|vs|versus|–|-)\s+(.+)', text, re.I)
                if m:
                    home, away = m.groups()
        if not home or not away:
            continue
        home = home.strip()
        away = away.strip()

        # ---- Thời gian (UTC) ----
        kickoff_utc = None
        meta = row.select_one('td.start-details meta[itemprop="startDate"]')
        if meta and meta.get('content'):
            iso = meta['content']
            try:
                # Xử lý định dạng ISO (có thể có Z)
                if iso.endswith('Z'):
                    iso = iso.replace('Z', '+00:00')
                dt = datetime.fromisoformat(iso)
                kickoff_utc = int(dt.timestamp())
            except:
                pass
        if not kickoff_utc:
            # Nếu không có ISO, bỏ qua (không xác định được giờ chính xác)
            continue

        # ---- Giải đấu ----
        comp_elem = row.select_one('td.competition-name span')
        if comp_elem:
            competition = comp_elem.text.strip()
        else:
            comp_elem = row.select_one('td.competition-name')
            competition = comp_elem.text.strip() if comp_elem else ""

        # ---- Kênh phát sóng ----
        channels = set()
        # Từ các ảnh logo
        imgs = row.select('td.channel-details img')
        for img in imgs:
            alt = img.get('alt', '').strip()
            title = img.get('title', '').strip()
            name = alt or title
            if name:
                # Bỏ hậu tố "logo"
                name = re.sub(r'\s+logo$', '', name, flags=re.I).strip()
                channels.add(name)
        # Từ text trong ô (có thể có tên kênh dạng chữ)
        chan_cell = row.select_one('td.channel-details')
        if chan_cell:
            text = chan_cell.get_text(separator=' ', strip=True)
            if text:
                # Tách bằng dấu phẩy hoặc xuống dòng
                for part in re.split(r'[,;]', text):
                    part = part.strip()
                    if part and not any(x in part.lower() for x in ['logo', 'image']):
                        channels.add(part)

        # Lọc giữ lại các kênh có trong UK_CHANNELS (tùy chọn, có thể bỏ qua nếu muốn giữ tất cả)
        # channels = [ch for ch in channels if any(uk in ch for uk in UK_CHANNELS)]  # nếu muốn lọc

        fixtures.append({
            'home': home,
            'away': away,
            'kickoff_utc': kickoff_utc,
            'competition': competition,
            'channels': list(channels)
        })

    return fixtures