# src/scrape_liveonsat.py
import os
import json
import re
import random
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# -------------------- CẤU HÌNH --------------------
DEFAULT_URL = "https://m.liveonsat.com/2day.php"
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = REPO_ROOT / "liveonsat_schedule.json"
DEBUG_HTML = REPO_ROOT / "liveonsat_debug.html"
DEBUG_PNG = REPO_ROOT / "liveonsat_debug.png"

# Múi giờ
BAGHDAD_TZ = timezone(timedelta(hours=3))
VIETNAM_TZ = timezone(timedelta(hours=7))

UA_POOL = [
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone14,3; U; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/602.1.50 (KHTML, like Gecko) Version/10.0 Mobile/19A346 Safari/602.1",
]

# -------------------- DANH SÁCH GIẢI ĐẤU ĐƯỢC PHÉP (giữ nguyên như cũ) --------------------
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

# -------------------- HÀM --------------------
def clean_text(t: str) -> str:
    if not t:
        return ""
    t = t.replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()

def get_html_with_playwright(url: str, timeout_ms: int = 60000) -> str:
    """Lấy HTML, không chờ selector đặc biệt, chỉ đợi tải xong"""
    ua = random.choice(UA_POOL)
    debug = os.environ.get("DEBUG_LIVEONSAT") == "1"
    print(f"[LiveOnSat] Đang tải {url} với UA={ua[:50]}...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-gpu"],
        )
        ctx = browser.new_context(
            user_agent=ua,
            locale="en-GB",
            timezone_id="Asia/Baghdad",
            viewport={"width": 1366, "height": 900},
            java_script_enabled=True,
        )
        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            # Đợi thêm 3s để các script chạy
            page.wait_for_timeout(3000)
            # Cuộn nhẹ để kích hoạt lazy-load
            for y in (600, 1200, 2000):
                page.evaluate(f"window.scrollTo(0, {y});")
                time.sleep(0.3)
            html = page.content()
            if debug:
                DEBUG_HTML.write_text(html, encoding="utf-8")
                page.screenshot(path=str(DEBUG_PNG), full_page=True)
                print("[LiveOnSat] Đã lưu debug html/png.")
            browser.close()
            return html
        except Exception as e:
            print(f"[LiveOnSat] Lỗi nghiêm trọng: {e}")
            if debug:
                try:
                    page.screenshot(path=str(REPO_ROOT / "liveonsat_error.png"), full_page=True)
                except:
                    pass
            browser.close()
            return "<html><body>FETCH_ERROR</body></html>"

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

def convert_to_vietnam_time(st_time_str: str, date_baghdad: datetime.date) -> str:
    """Chuyển giờ Baghdad (UTC+3) sang Việt Nam (UTC+7)"""
    try:
        hour, minute = map(int, st_time_str.split(":"))
        dt_baghdad = datetime.combine(date_baghdad, datetime.min.time().replace(hour=hour, minute=minute))
        dt_baghdad = dt_baghdad.replace(tzinfo=BAGHDAD_TZ)
        dt_vn = dt_baghdad.astimezone(VIETNAM_TZ)
        return dt_vn.strftime("%Y-%m-%d %H:%M")
    except:
        return f"{date_baghdad.isoformat()} {st_time_str}"

def parse_liveonsat(html: str):
    """Parse HTML, lọc trận đấu hợp lệ"""
    if "FETCH_ERROR" in html:
        print("[Parse] HTML bị lỗi fetch")
        return []
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text("\n")
    lines = [clean_text(l) for l in page_text.splitlines() if clean_text(l)]
    # Lọc bỏ dòng rác
    noise = {"Image", "HOME", "Full Site", "Daily TV", "Website Last updated", "Please Note:"}
    lines = [l for l in lines if l not in noise and not l.startswith("Website Last updated")]
    print(f"[Parse] Tổng số dòng sau lọc: {len(lines)}")

    matches_raw = []
    current_comp = None
    current_title = None
    current_time = None
    channels = []

    def flush():
        nonlocal current_title, current_time, channels
        if current_title and channels:
            matches_raw.append({
                "competition": current_comp,
                "title": current_title,
                "kickoff_baghdad": current_time,
                "channels_raw": channels[:]
            })
        current_title = None
        current_time = None
        channels = []

    for line in lines:
        if line.startswith("ST:"):
            m = re.search(r"ST:\s*([0-2]?\d:[0-5]\d)", line)
            if m:
                current_time = m.group(1)
            continue
        # Tiêu đề trận đấu (chứa vs hoặc v)
        if re.search(r"\b(vs|v)\b", line, re.IGNORECASE):
            flush()
            current_title = line
            continue
        # Giải đấu (có " - " và chưa có title)
        if " - " in line and not current_title and not line.startswith("ST:"):
            current_comp = line
            continue
        # Kênh
        if current_title:
            if line.lower() in ("watch", "details", "more", "back"):
                continue
            channels.append(line)
    flush()
    print(f"[Parse] Tìm thấy {len(matches_raw)} trận thô trước lọc")

    today_baghdad = datetime.now(BAGHDAD_TZ).date()
    result = []
    for m in matches_raw:
        league = normalize_league(m["competition"])
        if not is_match_allowed(league, m["title"]):
            continue
        dt_vn = convert_to_vietnam_time(m["kickoff_baghdad"], today_baghdad) if m["kickoff_baghdad"] else ""
        unique_channels = list(dict.fromkeys([ch for ch in m["channels_raw"] if ch and len(ch) > 1]))
        result.append({
            "league": league,
            "match": m["title"],
            "datetime": dt_vn,
            "channels": unique_channels
        })
    print(f"[Parse] Sau lọc: {len(result)} trận hợp lệ")
    return result

def main():
    url = os.environ.get("LOS_URL", DEFAULT_URL)
    html = get_html_with_playwright(url)
    items = parse_liveonsat(html)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Đã ghi {len(items)} trận vào {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
