import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
MODE = os.getenv("MODE", "daily")

FOREX_FACTORY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"

IMPORTANT_NEWS = [
    "CPI",
    "Core CPI",
    "PPI",
    "Core PPI",
    "Non-Farm",
    "Nonfarm",
    "NFP",
    "FOMC",
    "Federal Funds",
    "Interest Rate",
    "Powell",
    "Retail Sales",
    "Unemployment",
    "Average Hourly Earnings",
]

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": text
        },
        timeout=20
    )
    print(response.status_code)
    print(response.text)

def is_important(title):
    return any(k.lower() in title.lower() for k in IMPORTANT_NEWS)

def to_number(value):
    if not value or value == "-":
        return None

    try:
        clean = (
            value.replace("%", "")
            .replace("K", "")
            .replace("M", "")
            .replace("B", "")
            .replace(",", "")
            .strip()
        )
        return float(clean)
    except:
        return None

def gold_bias(title, actual, forecast):
    a = to_number(actual)
    f = to_number(forecast)

    if a is None or f is None:
        return "⏳ Chưa có Actual", 0

    title_low = title.lower()

    inflation_news = [
        "cpi",
        "ppi",
        "retail sales",
        "federal funds",
        "interest rate",
        "average hourly"
    ]

    jobs_news = [
        "non-farm",
        "nonfarm",
        "nfp"
    ]

    if any(x in title_low for x in inflation_news):
        if a > f:
            return "🔴 SELL GOLD BIAS - USD mạnh hơn", -3
        elif a < f:
            return "🟢 BUY GOLD BIAS - USD yếu hơn", 3

    if any(x in title_low for x in jobs_news):
        if a > f:
            return "🔴 SELL GOLD BIAS - việc làm mạnh", -3
        elif a < f:
            return "🟢 BUY GOLD BIAS - việc làm yếu", 3

    if "unemployment" in title_low:
        if a > f:
            return "🟢 BUY GOLD BIAS - thất nghiệp cao", 2
        elif a < f:
            return "🔴 SELL GOLD BIAS - thất nghiệp thấp", -2

    return "⚪ WAIT - chưa đủ rõ", 0

def parse_event_datetime(date_str, time_str):
    """
    ForexFactory XML thường dùng giờ New York/ET.
    Ở bản này chỉ parse để kiểm tra tương đối.
    Nếu lệch múi giờ, bước sau sẽ chỉnh JST chuẩn hơn.
    """
    try:
        raw = f"{date_str} {time_str}".strip()
        return datetime.strptime(raw, "%m-%d-%Y %I:%M%p")
    except:
        return None

def get_events():
    xml = requests.get(FOREX_FACTORY_URL, timeout=20).text
    soup = BeautifulSoup(xml, "xml")
    raw_events = soup.find_all("event")

    events = []

    for event in raw_events:
        currency_tag = event.find("country")
        impact_tag = event.find("impact")
        title_tag = event.find("title")
        date_tag = event.find("date")
        time_tag = event.find("time")
        forecast_tag = event.find("forecast")
        previous_tag = event.find("previous")
        actual_tag = event.find("actual")

        currency = currency_tag.text.strip() if currency_tag else ""
        impact = impact_tag.text.strip() if impact_tag else ""
        title = title_tag.text.strip() if title_tag else ""
        date = date_tag.text.strip() if date_tag else ""
        time = time_tag.text.strip() if time_tag else ""
        forecast = forecast_tag.text.strip() if forecast_tag else "-"
        previous = previous_tag.text.strip() if previous_tag else "-"
        actual = actual_tag.text.strip() if actual_tag else "-"

        if currency == "USD" and impact == "High" and is_important(title):
            events.append({
                "currency": currency,
                "impact": impact,
                "title": title,
                "date": date,
                "time": time,
                "forecast": forecast,
                "previous": previous,
                "actual": actual,
                "dt": parse_event_datetime(date, time),
            })

    return events

def daily_report(events):
    message = "🔥 HIGH IMPACT USD - TIN ẢNH HƯỞNG VÀNG\n\n"
    count = 0
    total_score = 0

    for e in events[:12]:
        bias, score = gold_bias(e["title"], e["actual"], e["forecast"])
        total_score += score

        message += f"🇺🇸 {e['date']} {e['time']} - USD time\n"
        message += f"{e['title']}\n"
        message += "Impact: 🔴 High\n"
        message += f"Actual: {e['actual']} | Forecast: {e['forecast']} | Previous: {e['previous']}\n"
        message += f"{bias}\n"
        message += f"Score: {score}\n\n"
        count += 1

    if count == 0:
        message += "⚠️ Không tìm thấy tin USD High Impact quan trọng cho vàng tuần này.\n"
    else:
        message += "----------------------\n"
        message += f"📊 Tổng Gold Score hiện tại: {total_score}\n"

        if total_score >= 6:
            message += "🟢 Kết luận: BUY GOLD BIAS mạnh\n"
        elif total_score <= -6:
            message += "🔴 Kết luận: SELL GOLD BIAS mạnh\n"
        elif total_score > 0:
            message += "🟢 Kết luận: BUY GOLD BIAS nhẹ\n"
        elif total_score < 0:
            message += "🔴 Kết luận: SELL GOLD BIAS nhẹ\n"
        else:
            message += "⚪ Kết luận: WAIT / NO TRADE\n"

    send_telegram(message)

def check_warning(events):
    now = datetime.utcnow()
    found = False

    for e in events:
        event_time = e["dt"]

        if event_time is None:
            continue

        minutes_left = (event_time - now).total_seconds() / 60

        if 25 <= minutes_left <= 35:
            message = "🚨 SẮP CÓ TIN USD HIGH IMPACT\n\n"
            message += f"Tin: {e['title']}\n"
            message += f"Thời gian: {e['date']} {e['time']} - USD time\n"
            message += f"Còn khoảng: {int(minutes_left)} phút\n\n"
            message += f"Forecast: {e['forecast']}\n"
            message += f"Previous: {e['previous']}\n\n"
            message += "⚠️ XAUUSD có thể biến động mạnh. Không FOMO trước tin.\n"

            send_telegram(message)
            found = True

    if not found:
        print("No warning event in 25-35 minutes.")

try:
    events = get_events()

    if MODE == "daily":
        daily_report(events)
    elif MODE == "check":
        check_warning(events)
    else:
        send_telegram(f"⚠️ MODE không hợp lệ: {MODE}")

except Exception as e:
    send_telegram(f"❌ ERROR\n{str(e)}")
