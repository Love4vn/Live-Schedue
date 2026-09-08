import requests
from bs4 import BeautifulSoup
import urllib3
import re
import json
from datetime import datetime, timedelta
import dateutil.parser

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===== CẤU HÌNH =====
USE_CURRENT_DATE_ONLY = False   # False: lấy ngày đầu tiên trên trang
FILTER_PAST_EVENTS = True       # True: chỉ lấy sự kiện chưa qua

# Danh sách các giải đấu bóng đá được phép (cấp cao nhất)
ALLOWED_LEAGUES = [
    "Premier League",          # đặc biệt: chỉ lấy của Anh
    "Serie A",
    "La Liga",
    "Bundesliga",
    "Ligue 1",
    "UEFA Champions League",
    "UEFA Europa League",
    "UEFA Europa Conference League",
    "UEFA Euro",
    "FA Cup",
    "League Cup",
    "International Friendly",
    "FIFA World Cup"
]

# Từ khóa loại trừ cho bóng đá (giải nữ, trẻ, hạng dưới)
EXCLUDE_WORDS = ["women", "u19", "u21", "youth", "u-", "nữ", "u20", "u17", "junior", "reserve"]

# Các tiền tố quốc gia không được phép đi kèm với "Premier League"
PREMIER_LEAGUE_EXCLUDED_PREFIXES = [
    "egyptian", "scottish", "welsh", "spanish", "italian", "german", "french",
    "dutch", "portuguese", "turkish", "russian", "ukrainian", "belgian", "swiss",
    "austrian", "danish", "swedish", "norwegian", "finnish", "irish", "greek",
    "czech", "polish", "hungarian", "romanian", "bulgarian", "croatian", "serbian",
    "slovenian", "slovakian", "israeli", "saudi", "qatari", "emirati", "chinese",
    "japanese", "korean", "australian", "brazilian", "argentine", "mexican",
    "american", "canadian", "indian", "pakistani", "bangladeshi", "south african"
]

# Danh mục cho phép (chuẩn hóa)
ALLOWED_CATEGORIES = {"all soccer events", "tennis"}

def normalize_category_name(name):
    if not name:
        return ""
    name = re.sub(r'[^a-zA-Z0-9\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name.lower()

def parse_day_title(day_title):
    try:
        dt = dateutil.parser.parse(day_title, fuzzy=True)
        return dt.date()
    except Exception:
        for fmt in ("%A, %B %d, %Y", "%A, %d %B %Y"):
            try:
                dt = datetime.strptime(day_title, fmt)
                return dt.date()
            except ValueError:
                continue
        return None

def is_valid_soccer_event(title):
    """Kiểm tra sự kiện bóng đá có thuộc giải đấu cho phép và không bị loại trừ."""
    if not title:
        return False

    title_lower = title.lower()

    # Loại bỏ nếu chứa từ khóa loại trừ
    for w in EXCLUDE_WORDS:
        if w in title_lower:
            return False

    # Kiểm tra từng giải đấu
    for league in ALLOWED_LEAGUES:
        # Xử lý đặc biệt cho "Premier League"
        if league == "Premier League":
            # Phải có "Premier League" nhưng không có tiền tố quốc gia bị cấm
            if re.search(r'\bPremier League\b', title, re.IGNORECASE):
                # Nếu có "English" hoặc "England" thì chấp nhận
                if re.search(r'\b(?:English|England)\b', title, re.IGNORECASE):
                    return True
                # Nếu không có, kiểm tra xem có tiền tố bị cấm không
                for prefix in PREMIER_LEAGUE_EXCLUDED_PREFIXES:
                    if re.search(r'\b' + prefix + r'\s+Premier League\b', title, re.IGNORECASE):
                        return False
                # Nếu không có tiền tố bị cấm, coi là Premier League Anh
                return True
            else:
                continue  # không tìm thấy "Premier League"
        else:
            # Các giải khác: dùng regex để khớp chính xác, không cho phép hạng dưới (số hoặc II)
            if re.search(r'\d', league):
                # Giải có số (ví dụ Ligue 1) -> khớp chính xác
                pattern = r'\b' + re.escape(league) + r'\b'
            else:
                # Giải không có số: không cho phép theo sau bởi số hoặc II
                pattern = r'\b' + re.escape(league) + r'\b(?!\s+[0-9]{1,2}\b|\s+II\b)'

            if re.search(pattern, title, re.IGNORECASE):
                return True

    return False

def get_schedule_api_json():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Connection": "keep-alive",
    })

    try:
        url = "https://dlhd.st/index.php"
        response = session.get(url, timeout=15, verify=False)
        response.raise_for_status()
        html_content = response.text
    except Exception as e:
        return {"error": f"Kết nối thất bại: {str(e)}"}

    soup = BeautifulSoup(html_content, "html.parser")
    days = soup.find_all("div", class_="schedule__day")

    now_utc = datetime.utcnow()
    today_utc = now_utc.date()
    current_time = now_utc.time()

    filtered_data = {}
    found_any_event = False

    for day in days:
        day_title_el = day.find("div", class_="schedule__dayTitle")
        day_title = day_title_el.get_text(strip=True) if day_title_el else ""
        if not day_title:
            continue

        day_date = parse_day_title(day_title)
        if day_date is None:
            print(f"⚠️ Không parse được ngày: '{day_title}'")
            continue

        if USE_CURRENT_DATE_ONLY:
            if day_date != today_utc:
                print(f"⏩ Bỏ qua ngày '{day_title}' (không phải hôm nay)")
                continue
        else:
            if filtered_data:
                break
            print(f"📅 Lấy ngày đầu tiên: {day_title}")

        print(f"📅 Đang xử lý: {day_title}")

        if day_title not in filtered_data:
            filtered_data[day_title] = {}

        categories = day.find_all("div", class_="schedule__category")
        for cat in categories:
            cat_header_el = cat.find("div", class_="card__meta")
            cat_name_raw = cat_header_el.get_text(strip=True) if cat_header_el else ""
            cat_name_norm = normalize_category_name(cat_name_raw)
            print(f"   📂 Danh mục thực tế: '{cat_name_raw}' -> chuẩn hóa: '{cat_name_norm}'")

            if cat_name_norm not in ALLOWED_CATEGORIES:
                continue

            print(f"   ✅ Chấp nhận danh mục: {cat_name_raw}")

            if cat_name_raw not in filtered_data[day_title]:
                filtered_data[day_title][cat_name_raw] = []

            events = cat.find_all("div", class_="schedule__event")
            for event in events:
                time_el = event.find("span", class_="schedule__time")
                raw_time = time_el.get_text(strip=True) if time_el else "00:00"

                try:
                    event_time = datetime.strptime(raw_time.strip(), "%H:%M").time()
                except Exception:
                    event_time = datetime.strptime("00:00", "%H:%M").time()

                title_el = event.find("span", class_="schedule__eventTitle")
                event_title = title_el.get_text(strip=True) if title_el else "No Title"

                # Lọc thời gian đã qua
                if FILTER_PAST_EVENTS:
                    if day_date == today_utc:
                        if event_time < current_time:
                            print(f"      ⏳ Bỏ qua (đã qua): {event_title} lúc {raw_time}")
                            continue
                    else:
                        if day_date < today_utc:
                            print(f"      ⏳ Bỏ qua (ngày cũ): {event_title}")
                            continue

                # Phân biệt danh mục để lọc giải đấu
                is_tennis = (cat_name_norm == "tennis")
                is_soccer = (cat_name_norm == "all soccer events")

                if is_soccer:
                    if not is_valid_soccer_event(event_title):
                        print(f"      ❌ Bỏ qua (không đúng giải): {event_title}")
                        continue
                elif is_tennis:
                    # Tennis: không lọc giải, giữ tất cả
                    pass
                else:
                    continue  # không nên xảy ra

                channels_list = []
                channels_div = event.find("div", class_="schedule__channels")
                if channels_div:
                    channel_links = channels_div.find_all("a")
                    for ch in channel_links:
                        ch_name = ch.get_text(strip=True)
                        ch_href = ch.get("href", "")
                        ch_id = ""
                        if "id=" in ch_href:
                            id_match = re.search(r'id=(\d+)', ch_href)
                            ch_id = id_match.group(1) if id_match else ch_href.split("id=")[-1]
                        else:
                            id_match = re.search(r'(\d+)', ch_href.split("/")[-1])
                            ch_id = id_match.group(1) if id_match else ch_href.split("/")[-1].replace(".php", "")
                        channels_list.append({
                            "channel_name": ch_name,
                            "channel_id": ch_id
                        })

                event_data = {
                    "time": raw_time,
                    "event": event_title,
                    "channels": channels_list
                }
                filtered_data[day_title][cat_name_raw].append(event_data)
                found_any_event = True
                print(f"      ✅ Đã thêm: {event_title} lúc {raw_time}")

        if not USE_CURRENT_DATE_ONLY and filtered_data:
            break

    if not found_any_event:
        print("ℹ️ Không tìm thấy sự kiện nào phù hợp.")

    return filtered_data

if __name__ == "__main__":
    api_data = get_schedule_api_json()
    output_file = "daddylive_schedule.json"

    if "error" in api_data:
        print(f"❌ Lỗi: {api_data['error']}")
    else:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(api_data, f, ensure_ascii=False, indent=4)
        print(f"💾 Đã lưu dữ liệu vào {output_file}")

        total = 0
        for day, categories in api_data.items():
            for cat, events in categories.items():
                total += len(events)
        print(f"📊 Tổng số sự kiện đã lọc: {total}")
