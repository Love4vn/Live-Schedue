import requests
from bs4 import BeautifulSoup
import urllib3
import re
import json
from datetime import datetime, timedelta
import dateutil.parser  # thêm thư viện để parse ngày tháng linh hoạt

# Tắt cảnh báo SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def parse_day_title(day_title):
    """
    Chuyển đổi chuỗi tiêu đề ngày (ví dụ: 'Friday, April 17, 2020')
    thành đối tượng datetime (UTC).
    """
    try:
        # Dùng dateutil để parse nhiều định dạng
        dt = dateutil.parser.parse(day_title, fuzzy=True)
        # Chỉ lấy ngày, không lấy giờ
        return dt.date()
    except Exception:
        # Nếu không parse được, thử dùng regex hoặc các định dạng cố định
        # Một số định dạng có thể là: "Friday, 17 April 2020"
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

    # Lọc danh mục: chỉ lấy hai loại này
    ALLOWED_CATEGORIES = {"All Soccer Events", "Tennis"}

    try:
        url = "https://dlhd.st/index.php"
        response = session.get(url, timeout=15, verify=False)
        response.raise_for_status()
        html_content = response.text
    except Exception as e:
        return {"error": f"Kết nối thất bại: {str(e)}"}

    soup = BeautifulSoup(html_content, "html.parser")
    days = soup.find_all("div", class_="schedule__day")

    # Lấy ngày hiện tại (UTC)
    today_utc = datetime.utcnow().date()
    current_time = datetime.utcnow().time()

    filtered_data = {}

    for day in days:
        day_title_el = day.find("div", class_="schedule__dayTitle")
        day_title = day_title_el.get_text(strip=True) if day_title_el else ""

        # Parse ngày từ tiêu đề
        day_date = parse_day_title(day_title)
        if day_date is None or day_date != today_utc:
            continue  # bỏ qua ngày khác hôm nay

        # Nếu là hôm nay, tạo key cho ngày
        if day_title not in filtered_data:
            filtered_data[day_title] = {}

        categories = day.find_all("div", class_="schedule__category")
        for cat in categories:
            cat_header_el = cat.find("div", class_="card__meta")
            cat_name = cat_header_el.get_text(strip=True) if cat_header_el else ""

            # Chỉ giữ danh mục cho phép
            if cat_name not in ALLOWED_CATEGORIES:
                continue

            if cat_name not in filtered_data[day_title]:
                filtered_data[day_title][cat_name] = []

            events = cat.find_all("div", class_="schedule__event")
            for event in events:
                time_el = event.find("span", class_="schedule__time")
                raw_time = time_el.get_text(strip=True) if time_el else "00:00"

                # Giữ nguyên múi giờ UTC (không cộng thêm 7)
                try:
                    event_time = datetime.strptime(raw_time.strip(), "%H:%M").time()
                except Exception:
                    event_time = datetime.strptime("00:00", "%H:%M").time()

                # So sánh thời gian sự kiện với thời gian hiện tại (UTC)
                # Nếu sự kiện đã qua (nhỏ hơn current_time) thì bỏ qua
                if event_time < current_time:
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
                    "time": raw_time,  # giờ gốc UTC
                    "event": event_title,
                    "channels": channels_list
                }
                filtered_data[day_title][cat_name].append(event_data)

    # Nếu không có sự kiện nào phù hợp, trả về object rỗng
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
        print(json.dumps(api_data, ensure_ascii=False, indent=4))
