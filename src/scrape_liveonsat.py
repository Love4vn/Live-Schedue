# src/scrape_liveonsat.py
import os
import json
import re
import random
import time
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

# -------------------- CẤU HÌNH --------------------
DEFAULT_URL = "https://m.liveonsat.com/2day.php"
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = REPO_ROOT / "liveonsat_schedule.json"
DEBUG_HTML = REPO_ROOT / "liveonsat_debug.html"
DEBUG_PNG = REPO_ROOT / "liveonsat_debug.png"

# User-Agent pool (mobile)
UA_POOL = [
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone14,3; U; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/602.1.50 (KHTML, like Gecko) Version/10.0 Mobile/19A346 Safari/602.1",
]

# -------------------- DANH SÁCH GIẢI ĐẤU ĐƯỢC PHÉP (giữ nguyên) --------------------
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

def get_html_with_playwright(url: str, timeout_ms: int = 90000) -> str:
    """Lấy HTML từ LiveOnSat với độ chờ tốt hơn"""
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
            viewport={"width": 1366, "height": 900},
            java_script_enabled=True,
        )
        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            # Cuộn trang nhiều lần để tải nội dung lazy
            for y in range(0, 5000, 500):
                page.evaluate(f"window.scrollTo(0, {y});")
                time.sleep(0.2)
            # Đợi thêm 2 giây để ổn định
            page.wait_for_timeout(2000)
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

def parse_liveonsat(html: str):
    """Parser mới dựa trên regex và cấu trúc dòng thực tế"""
    if "FETCH_ERROR" in html:
        print("[Parse] HTML bị lỗi fetch")
        return []

    # Lấy tất cả văn bản hiển thị, loại bỏ thẻ script/style
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for script in soup(["script", "style"]):
        script.decompose()
    raw_text = soup.get_text("\n")
    lines = [clean_text(l) for l in raw_text.splitlines() if clean_text(l)]
    
    # Lọc bỏ các dòng rác
    noise = {"Image", "HOME", "Full Site", "Daily TV", "Website Last updated", "Please Note:", "LIVE", "Discover more"}
    lines = [l for l in lines if l not in noise and not l.startswith("Website Last updated") and not l.startswith("Timezone")]
    print(f"[Parse] Tổng số dòng sau lọc: {len(lines)}")

    # Duyệt tìm các dòng có ST: (giờ)
    # Mỗi trận thường có cấu trúc:
    # [tên giải] (có dấu - hoặc không)
    # [tên trận] chứa "v" hoặc "vs"
    # [LIVE] ST: HH:MM
    matches_raw = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Tìm dòng chứa "ST:"
        st_match = re.search(r"ST:\s*([0-2]?\d:[0-5]\d)", line)
        if st_match:
            kickoff = st_match.group(1)
            # Lấy dòng trước đó làm tên trận (nếu có)
            title = lines[i-1] if i-1 >= 0 else ""
            # Lấy dòng trước title làm giải (nếu có và chứa dấu -)
            competition = ""
            if i-2 >= 0 and " - " in lines[i-2]:
                competition = lines[i-2]
            elif i-3 >= 0 and " - " in lines[i-3]:
                competition = lines[i-3]
            
            # Kiểm tra title có chứa "v" hoặc "vs" không
            if re.search(r"\b(vs|v)\b", title, re.IGNORECASE):
                matches_raw.append({
                    "competition": competition,
                    "title": title,
                    "kickoff_baghdad": kickoff,   # thực tế là giờ Việt Nam (GMT+7)
                    "channels_raw": []  # kênh không cần thiết nếu không có, nhưng giữ cấu trúc
                })
        i += 1

    print(f"[Parse] Tìm thấy {len(matches_raw)} trận thô trước lọc")

    # Lọc theo giải và đội
    result = []
    for m in matches_raw:
        league = normalize_league(m["competition"])
        if not is_match_allowed(league, m["title"]):
            continue
        # Giờ đã là giờ Việt Nam (trang hiển thị GMT+7), không cần chuyển đổi
        # Định dạng datetime: lấy ngày hiện tại + giờ
        today_str = datetime.now().strftime("%Y-%m-%d")
        dt_vn = f"{today_str} {m['kickoff_baghdad']}"
        result.append({
            "league": league,
            "match": m["title"],
            "datetime": dt_vn,
            "channels": []  # hiện tại không có thông tin kênh trong ảnh, có thể bỏ qua hoặc để trống
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
