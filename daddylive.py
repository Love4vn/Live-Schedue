import requests
from bs4 import BeautifulSoup
import urllib3
import re
import json
from datetime import datetime, timedelta
import dateutil.parser

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# === CẤU HÌNH ===
# True: chỉ lấy sự kiện trong ngày hiện tại (UTC)
# False: lấy ngày đầu tiên xuất hiện trên trang (có thể là ngày hôm qua)
USE_CURRENT_DATE_ONLY = False  # Bạn có thể đổi thành False nếu muốn lấy ngày đang hiển thị

ALLOWED_CATEGORIES = {"All Soccer Events", "Tennis"}

def parse_day_title(day_title):
    """Parse tiêu đề ngày (ví dụ: 'Friday, April 17, 2020') thành đối tượng date."""
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

    # Lấy thời gian hiện tại (UTC)
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
            # Nếu chưa có dữ liệu, lấy ngày đầu tiên (và chỉ lấy ngày đó)
            if filtered_data:
                break  # chỉ lấy ngày đầu tiên
            # nếu chưa có, tiếp tục xử lý ngày này

        print(f"📅 Đang xử lý ngày: {day_title}")

        if day_title not in filtered_data:
            filtered_data[day_title] = {}

        categories = day.find_all("div", class_="schedule__category")
        for cat in categories:
            cat_header_el = cat.find("div", class_="card__meta")
            cat_name = cat_header_el.get_text(strip=True) if cat_header_el else ""

            if cat_name not in ALLOWED_CATEGORIES:
                continue

            print(f"   📂 Danh mục: {cat_name}")
            if cat_name not in filtered_data[day_title]:
                filtered_data[day_title][cat_name] = []

            events = cat.find_all("div", class_="schedule__event")
            for event in events:
                time_el = event.find("span", class_="schedule__time")
                raw_time = time_el.get_text(strip=True) if time_el else "00:00"

                try:
                    event_time = datetime.strptime(raw_time.strip(), "%H:%M").time()
                except Exception:
                    event_time = datetime.strptime("00:00", "%H:%M").time()

                # So sánh thời gian: nếu sự kiện đã qua thì bỏ qua
                if USE_CURRENT_DATE_ONLY:
                    # Chỉ so sánh giờ trong ngày (vì đã lọc đúng ngày)
                    if event_time < current_time:
                        print(f"      ⏳ Bỏ qua sự kiện '{event_title}' đã qua (giờ {raw_time})")
                        continue
                else:
                    # Nếu lấy ngày đầu tiên, cần so sánh cả ngày và giờ
                    event_datetime = datetime.combine(day_date, event_time)
                    if event_datetime < now_utc:
                        print(f"      ⏳ Bỏ qua sự kiện đã qua: {event_title} lúc {raw_time}")
                        continue

                title_el = event.find("span", class_="schedule__eventTitle")
                event_title = title_el.get_text(strip=True) if title_el else "No Title"

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
                filtered_data[day_title][cat_name].append(event_data)
                found_any_event = True
                print(f"      ✅ Đã thêm sự kiện: {event_title} lúc {raw_time}")

        # Nếu không lọc theo ngày hiện tại, chỉ xử lý một ngày đầu tiên
        if not USE_CURRENT_DATE_ONLY and filtered_data:
            break

    if not found_any_event:
        print("ℹ️ Không tìm thấy sự kiện nào thuộc danh mục cho phép (hoặc tất cả đã qua).")

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
        # In ra số lượng sự kiện
        total = sum(len(events) for day in api_data.values() for cat in day.values() for events in [cat] if isinstance(cat, list))
        print(f"📊 Tổng số sự kiện đã lọc: {total}")
