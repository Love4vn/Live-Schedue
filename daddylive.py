import requests
from bs4 import BeautifulSoup
import urllib3
import re
import json
from datetime import datetime, timedelta
import dateutil.parser

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# === CẤU HÌNH ===
USE_CURRENT_DATE_ONLY = False   # False: lấy ngày đầu tiên trên trang (hiện là 4/9)
FILTER_PAST_EVENTS = True       # True: chỉ lấy sự kiện chưa qua; False: lấy tất cả

ALLOWED_CATEGORIES = {"all soccer events", "tennis"}  # chuẩn hóa về chữ thường

def normalize_category_name(name):
    """Chuẩn hóa tên danh mục: xóa ký tự đặc biệt, khoảng trắng thừa, chuyển chữ thường."""
    if not name:
        return ""
    name = re.sub(r'[^a-zA-Z0-9\s]', '', name)  # loại bỏ ký tự đặc biệt
    name = re.sub(r'\s+', ' ', name).strip()    # gộp khoảng trắng
    return name.lower()

def parse_day_title(day_title):
    """Chuyển tiêu đề ngày (vd: 'Friday, April 17, 2020') thành đối tượng date."""
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

        # Lọc ngày theo chế độ
        if USE_CURRENT_DATE_ONLY:
            if day_date != today_utc:
                print(f"⏩ Bỏ qua ngày '{day_title}' (không phải hôm nay)")
                continue
        else:
            if filtered_data:  # đã có dữ liệu từ ngày đầu tiên -> thoát
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

            # Dùng tên gốc làm key để giữ nguyên hiển thị
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

                # Lọc sự kiện đã qua nếu bật
                if FILTER_PAST_EVENTS:
                    # Nếu ngày xử lý là ngày hiện tại, so sánh giờ
                    if day_date == today_utc:
                        if event_time < current_time:
                            print(f"      ⏳ Bỏ qua sự kiện đã qua: {event_title} lúc {raw_time}")
                            continue
                    else:
                        # Ngày khác (ví dụ hôm qua) -> coi như đã qua
                        if day_date < today_utc:
                            print(f"      ⏳ Bỏ qua sự kiện ngày cũ: {event_title}")
                            continue
                        # Nếu ngày trong tương lai (hiếm), giữ nguyên

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

        # Nếu đang lấy ngày đầu tiên, dừng sau khi xử lý xong ngày đó
        if not USE_CURRENT_DATE_ONLY and filtered_data:
            break

    if not found_any_event:
        print("ℹ️ Không tìm thấy sự kiện nào thuộc danh mục 'All Soccer Events' hoặc 'Tennis' (hoặc đã qua).")

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
