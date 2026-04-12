import os
import json
import re
import time
from pathlib import Path
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# -------------------- CẤU HÌNH --------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = REPO_ROOT / "liveonsat_schedule.json"

# Giả sử giờ trên livesoccertv là UTC, chuyển sang VN (UTC+7)
TIME_OFFSET_HOURS = 7

# -------------------- DANH SÁCH GIẢI ĐẤU ĐƯỢC PHÉP --------------------
ALLOWED_TENNIS_TOURNAMENTS = {
    "atp", "atp tour", "atp world tour", "grand slam", "australian open",
    "roland garros", "french open", "wimbledon", "us open", "nitto atp finals",
    "atp masters", "atp 1000", "atp 500", "atp 250"
}
ALLOWED_FOOTBALL_LEAGUES = {
    "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "UEFA Euro", "FA Cup", "League Cup", "International Friendly"
}
PREMIER_LEAGUE_TEAMS = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton"
}
ALLOWED_TEAMS_PER_LEAGUE = {
    "Premier League": PREMIER_LEAGUE_TEAMS,
    "Serie A": {"inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"},
    "La Liga": {"barcelona", "real madrid", "atletico madrid"},
    "Bundesliga": {"bayern munich", "borussia dortmund", "bayer leverkusen"},
    "Ligue 1": {"psg", "paris saint-germain", "olympique marseille", "marseille"},
    "FA Cup": PREMIER_LEAGUE_TEAMS,
    "League Cup": PREMIER_LEAGUE_TEAMS
}
ALLOWED_NON_EURO_TEAMS = {"argentina", "brazil", "japan", "south korea"}

# -------------------- HÀM XỬ LÝ --------------------
def normalize_league(comp_raw: str):
    comp_lower = comp_raw.lower()
    if "premier league" in comp_lower:
        return "Premier League"
    if "serie a" in comp_lower:
        return "Serie A"
    if "la liga" in comp_lower:
        return "La Liga"
    if "bundesliga" in comp_lower:
        return "Bundesliga"
    if "ligue 1" in comp_lower:
        return "Ligue 1"
    if "champions league" in comp_lower:
        return "UEFA Champions League"
    if "europa league" in comp_lower and "conference" not in comp_lower:
        return "UEFA Europa League"
    if "conference league" in comp_lower:
        return "UEFA Europa Conference League"
    if "uefa euro" in comp_lower or "euro 20" in comp_lower:
        return "UEFA Euro"
    if "fa cup" in comp_lower:
        return "FA Cup"
    if "league cup" in comp_lower:
        return "League Cup"
    if "international friendly" in comp_lower or "friendly" in comp_lower:
        return "International Friendly"
    for keyword in ALLOWED_TENNIS_TOURNAMENTS:
        if keyword in comp_lower:
            return "Tennis"
    return None

def is_match_allowed(league: str, title: str) -> bool:
    if not league:
        return False
    title_lower = title.lower()
    if league == "Tennis":
        return True
    if league in ALLOWED_FOOTBALL_LEAGUES:
        if league in ("UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League", "UEFA Euro"):
            return True
        if league == "International Friendly":
            return any(team in title_lower for team in ALLOWED_NON_EURO_TEAMS)
        if league in ALLOWED_TEAMS_PER_LEAGUE:
            allowed_teams = ALLOWED_TEAMS_PER_LEAGUE[league]
            return any(team in title_lower for team in allowed_teams)
        return False
    return False

def convert_to_vietnam_time(time_str: str, date_str: str) -> str:
    """Chuyển giờ từ UTC sang VN (UTC+7)"""
    try:
        # Xử lý AM/PM
        is_pm = False
        if "PM" in time_str and "12" not in time_str:
            is_pm = True
        time_clean = re.sub(r"[AP]M", "", time_str).strip()
        hour, minute = map(int, time_clean.split(":"))
        if is_pm:
            hour += 12
        dt_utc = datetime.strptime(f"{date_str} {hour}:{minute}", "%Y-%m-%d %H:%M")
        dt_vn = dt_utc + timedelta(hours=TIME_OFFSET_HOURS)
        return dt_vn.strftime("%Y-%m-%d %H:%M")
    except Exception as e:
        print(f"[Lỗi chuyển giờ] {e}")
        return f"{date_str} {time_str}"

def get_html_with_playwright(url: str):
    """Dùng Playwright lấy HTML, không cần giải captcha"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        # Cuộn để tải toàn bộ nội dung
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(3)
        html = page.content()
        browser.close()
        return html

def scrape_livesoccertv():
    url = "https://www.livesoccertv.com/schedules/"
    print(f"[LiveSoccerTV] Đang tải {url} bằng Playwright...")
    html = get_html_with_playwright(url)
    soup = BeautifulSoup(html, "html.parser")
    
    matches = []
    # Duyệt tất cả các hàng có class "match-row" hoặc "match"
    rows = soup.select("tr.match, .match-row, .match")
    print(f"[LiveSoccerTV] Tìm thấy {len(rows)} hàng trận đấu")
    
    for row in rows:
        try:
            # Giải đấu
            league_tag = row.select_one(".competition a, .league a")
            league_raw = league_tag.text.strip() if league_tag else ""
            league = normalize_league(league_raw)
            if not league:
                continue
            
            # Tên trận
            home_tag = row.select_one(".home-team a, .team-home a, .home a")
            away_tag = row.select_one(".away-team a, .team-away a, .away a")
            if not home_tag or not away_tag:
                continue
            title = f"{home_tag.text.strip()} vs {away_tag.text.strip()}"
            
            # Lọc theo giải và đội
            if not is_match_allowed(league, title):
                continue
            
            # Giờ
            time_tag = row.select_one(".time, .match-time")
            time_str = time_tag.text.strip() if time_tag else ""
            # Ngày (mặc định hôm nay)
            date_str = datetime.now().strftime("%Y-%m-%d")
            dt_vn = convert_to_vietnam_time(time_str, date_str) if time_str else ""
            
            # Kênh
            channels = [ch.text.strip() for ch in row.select(".channel a, .tv-station a")]
            
            matches.append({
                "league": league,
                "match": title,
                "datetime": dt_vn,
                "channels": channels
            })
        except Exception as e:
            print(f"[Lỗi parse một trận] {e}")
            continue
    
    return matches

def main():
    items = scrape_livesoccertv()
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Đã ghi {len(items)} trận vào {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
