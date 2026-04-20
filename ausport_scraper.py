from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta
import pytz
import re
import os

# ====================== CẤU HÌNH ======================
DAY_ORDER = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
TIME_RANGE_HOURS = 48
OUTPUT_FILE = 'ausport_schedule.json'

MONTH_MAP = {
    'January': 0, 'Jan': 0, 'February': 1, 'Feb': 1, 'March': 2, 'Mar': 2,
    'April': 3, 'Apr': 3, 'May': 4, 'June': 5, 'Jun': 5, 'July': 6, 'Jul': 6,
    'August': 7, 'Aug': 7, 'September': 8, 'Sep': 8, 'Sept': 8,
    'October': 9, 'Oct': 9, 'November': 10, 'Nov': 10,
    'December': 11, 'Dec': 11
}

FOOTBALL_CONFIG = {
    'leagues': {
        'Premier League': ['arsenal', 'aston villa', 'bournemouth', 'brentford', 'brighton', 'chelsea',
                           'crystal palace', 'everton', 'fulham', 'leeds united', 'liverpool', 'manchester city',
                           'manchester united', 'newcastle', 'nottingham forest', 'sunderland', 'tottenham hotspur',
                           'west ham united', 'wolverhampton'],
        'Serie A': ['inter milan', 'ac milan', 'napoli', 'juventus', 'roma', 'atalanta', 'lazio'],
        'La Liga': ['barcelona', 'real madrid', 'atlético'],
        'Bundesliga': ['bayern', 'borussia dortmund', 'bayer leverkusen'],
        'Ligue 1': ['psg', 'olympique marseille'],
        'UEFA Champions League': 'all',
        'UEFA Europa League': 'all',
        'UEFA Europa Conference League': 'all',
        'World Cup': 'all',
        'EURO': 'all',
        'UEFA European Championship': 'all',
    },
    'friendlyAllowedTeams': ['argentina', 'brazil', 'japan', 'south korea', 'nhật bản', 'hàn quốc'],
    'excludeKeywords': ['u18', 'u19', 'u20', 'u21', 'u23', 'women', 'girls', 'boys', 'youth', 'junior', 'reserves', 'woman']
}

def is_football_relevant(competition, home, away, title):
    comp = (competition or '').lower()
    h = (home or '').lower()
    a = (away or '').lower()
    t = (title or '').lower()

    # Loại trừ từ khóa
    if any(kw in comp or kw in t for kw in FOOTBALL_CONFIG['excludeKeywords']):
        return False

    # Giải đặc biệt
    special = ['uefa champions league', 'uefa europa league', 'uefa europa conference league',
               'world cup', 'euro', 'uefa european championship']
    if any(s in comp for s in special):
        return True

    # Kiểm tra theo league + team
    for league, teams in FOOTBALL_CONFIG['leagues'].items():
        if league.lower() in comp:
            if teams == 'all':
                return True
            team_list = [t.lower() for t in teams]
            if any(team in h or team in a for team in team_list):
                return True

    # Friendly
    if 'friendly' in comp or 'friendly' in t:
        if any(team in h or team in a for team in FOOTBALL_CONFIG['friendlyAllowedTeams']):
            return True
    return False

def is_tennis_relevant(sport, competition):
    s = (sport or '').lower()
    c = (competition or '').lower()
    if s != 'tennis':
        return False
    return any(k in c for k in ['atp', 'wta', 'grand slam'])

def is_event_relevant(sport, competition, home, away, title):
    # FIX: Nếu competition chứa Premier League thì coi là football luôn (bypass sport detection)
    if 'premier league' in (competition or '').lower():
        return is_football_relevant(competition, home, away, title)
    s = (sport or '').lower()
    if s in ['soccer', 'football']:
        return is_football_relevant(competition, home, away, title)
    if s == 'tennis':
        return is_tennis_relevant(sport, competition)
    return False

def convert_aedt_to_vietnam(base_date, time_str):
    if not time_str:
        return None
    match = re.match(r'^(\d{1,2}):(\d{2})(AM|PM)$', time_str, re.I)
    if not match:
        return None
    hour, minute, ampm = match.groups()
    hour = int(hour)
    minute = int(minute)
    if ampm.upper() == 'PM' and hour != 12:
        hour += 12
    if ampm.upper() == 'AM' and hour == 12:
        hour = 0

    aedt = pytz.timezone('Australia/Sydney')
    vietnam = pytz.timezone('Asia/Ho_Chi_Minh')

    dt = datetime.combine(base_date.date(), datetime.min.time())
    dt = aedt.localize(dt.replace(hour=hour, minute=minute))
    dt_vn = dt.astimezone(vietnam)
    return dt_vn

def get_vietnam_info(base_date, time_str):
    dt = convert_aedt_to_vietnam(base_date, time_str)
    if not dt:
        return None
    return {
        'datetime': dt.isoformat(),
        'jam': dt.strftime('%H:%M'),
        'tanggal': dt.strftime('%d/%m/%Y')
    }

def resolve_base_date(page_suffix):
    # Fallback đơn giản
    now = datetime.now(pytz.timezone('Australia/Sydney'))
    day_map = {'sun': 0, 'mon': 1, 'tue': 2, 'wed': 3, 'thu': 4, 'fri': 5, 'sat': 6}
    target = day_map[page_suffix]
    diff = (target - now.weekday()) % 7
    base = now + timedelta(days=diff)
    return base.replace(hour=0, minute=0, second=0, microsecond=0).date()

def extract_home_away(match_text):
    """FIX: Hỗ trợ cả ' - ', ' V ', ' vs ', 'v' """
    match_text = match_text.strip()
    for sep in [' V ', ' vs ', ' - ', ' v ']:
        if sep in match_text:
            parts = match_text.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    # Không có separator thì trả về toàn bộ làm home (away rỗng)
    return match_text, ''

def scrape_day(page_suffix):
    url = f'https://ausportguide.com/live-sports-tv-guide/{page_suffix}'
    print(f'🔍 Scraping: {url}')
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/134.0 Safari/537.36'
    }
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    base_date = resolve_base_date(page_suffix)
    rows = []

    # ====================== MAIN EVENTS ======================
    current_competition = ''
    for el in soup.select('h3, .leagueTitle, div.list-group-item.d-flex.gap-3.shadow-sm'):
        if 'leagueTitle' in el.get('class', []):
            current_competition = el.find('span', class_='align-middle')
            current_competition = current_competition.get_text(strip=True) if current_competition else ''
            continue

        if 'list-group-item' in el.get('class', []):
            time_aedt = el.select_one('.eventTime')
            time_aedt = time_aedt.get_text(strip=True) if time_aedt else ''

            event_text = el.select_one('.eventText')
            if not event_text or not time_aedt:
                continue

            # FIX: Lấy home/away linh hoạt
            team_divs = event_text.find_all('div', recursive=False)
            home_raw = team_divs[0].get_text(strip=True) if team_divs else ''
            away_raw = team_divs[1].get_text(strip=True) if len(team_divs) > 1 else ''
            if not away_raw:  # fallback dùng text toàn bộ
                home_raw, away_raw = extract_home_away(home_raw)

            title = event_text.select_one('div.fs-10 i')
            title = title.get_text(strip=True) if title else ''

            # Channels
            channels = [img.get('title') or img.get('alt') or '' for img in el.select('img.stationImg')]
            channels = ' | '.join([c.replace('Live on', '').strip() for c in channels if c])

            # Sport (có thể rỗng → fallback sau)
            sport = ''
            # Thử tìm sport theo cấu trúc cũ
            panel = el.find_parent('div', class_='panelLeague')
            if panel:
                panel_type = panel.find_previous_sibling('div', class_='panelType')
                if panel_type:
                    h3 = panel_type.find('h3')
                    if h3:
                        sport = h3.get_text(strip=True)

            vn_info = get_vietnam_info(base_date, time_aedt)
            rows.append({
                'day': page_suffix,
                'sport': sport,
                'competition': current_competition,
                'home': home_raw,
                'away': away_raw,
                'title': title,
                'channels': channels,
                'vietnam_jam': vn_info['jam'] if vn_info else '',
                'vietnam_tanggal': vn_info['tanggal'] if vn_info else '',
                'vietnam_datetime': vn_info['datetime'] if vn_info else None,
            })

    # ====================== HOT EVENTS ======================
    for item in soup.select('.panel-body-desktop .hotEvents .list-group-item'):
        open_link = item.select_one('.openUrl')
        if not open_link:
            continue
        line1 = open_link.select_one('.eventText > div')
        line1 = line1.get_text(strip=True).replace('\n', ' ') if line1 else ''
        line2 = open_link.select_one('.eventText > div:nth-child(2)')
        line2 = line2.get_text(strip=True).replace('\n', ' ') if line2 else ''

        left, match_raw = (line1.split('|', 1) + [''])[0:2]
        sport = line2.split('|')[0].strip() if '|' in line2 else ''
        league = line2.split('|')[1].strip() if '|' in line2 else ''

        time_aedt = re.search(r'from\s+(\d{1,2}:\d{2}(?:AM|PM))', left, re.I)
        time_aedt = time_aedt.group(1).upper() if time_aedt else ''

        base_date_hot = datetime.now(pytz.timezone('Australia/Sydney')).date()  # hot events thường là today/tomorrow
        home, away = extract_home_away(match_raw)

        vn_info = get_vietnam_info(base_date_hot, time_aedt)
        rows.append({
            'sport': sport,
            'competition': league or 'Hot Events',
            'home': home,
            'away': away,
            'channels': 'Hot',
            'vietnam_jam': vn_info['jam'] if vn_info else '',
            'vietnam_tanggal': vn_info['tanggal'] if vn_info else '',
            'vietnam_datetime': vn_info['datetime'] if vn_info else None,
        })

    print(f'   → Rows for {page_suffix}: {len(rows)}')
    return rows

# ====================== MAIN ======================
if __name__ == '__main__':
    all_rows = []
    for d in DAY_ORDER:
        try:
            rows = scrape_day(d)
            all_rows.extend(rows)
        except Exception as e:
            print(f'❌ Lỗi {d}: {e}')

    # Lọc football/tennis
    filtered = [r for r in all_rows if is_event_relevant(r['sport'], r['competition'], r['home'], r['away'], r['title'])]
    print(f'✅ After sport/league filter: {len(filtered)}')

    # Lọc trong 48h
    now = datetime.now(pytz.timezone('Asia/Ho_Chi_Minh'))
    filtered = [r for r in filtered if r['vietnam_datetime'] and
                0 <= (datetime.fromisoformat(r['vietnam_datetime'].replace('Z', '+00:00')) - now).total_seconds() / 3600 <= TIME_RANGE_HOURS]
    print(f'✅ After 48h filter: {len(filtered)}')

    # Dedup
    seen = set()
    final = []
    for r in filtered:
        key = f"{r['vietnam_tanggal']}|{r['vietnam_jam']}|{r['sport']}|{r['competition']}|{r['home']}|{r['away']}".lower()
        if key not in seen:
            seen.add(key)
            final.append(r)

    print(f'✅ After deduplication: {len(final)}')

    # Sort theo thời gian
    final.sort(key=lambda x: x['vietnam_datetime'] or '')

    # Xuất JSON
    output = [{
        'competition': r['competition'],
        'home': r['home'],
        'away': r['away'],
        'vietnam_time': r['vietnam_jam'],
        'vietnam_date': r['vietnam_tanggal'],
        'channels': r['channels'],
        'sport': r['sport'],
    } for r in final]

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f'🎉 JSON đã ghi: {OUTPUT_FILE}')
    print('📌 Trận Crystal Palace V West Ham United đã được lấy (nếu trong 48h)!')
