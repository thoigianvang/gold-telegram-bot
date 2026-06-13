import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

IMPORTANT_NEWS = [
    "CPI", "Core CPI", "PPI", "Core PPI",
    "Non-Farm", "Nonfarm", "NFP",
    "FOMC", "Federal Funds", "Interest Rate",
    "Powell", "Retail Sales", "Unemployment"
]

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=20)

def is_important(title):
    return any(k.lower() in title.lower() for k in IMPORTANT_NEWS)

def to_number(value):
    if not value or value == "-":
        return None
    try:
        return float(value.replace("%", "").replace("K", "").replace("M", "").replace("B", "").strip())
    except:
        return None

def gold_bias(title, actual, forecast):
    a = to_number(actual)
    f = to_number(forecast)

    if a is None or f is None:
        return "⏳ Chưa có Actual", 0

    title_low = title.lower()

    hot_is_bad_for_gold = ["cpi", "ppi", "retail sales", "federal funds", "interest rate", "average hourly"]
    jobs_strong_bad_for_gold = ["non-farm", "nonfarm", "nfp"]

    if any(x in title_low for x in hot_is_bad_for_gold):
        if a > f:
            return "🔴 SELL GOLD BIAS - USD mạnh hơn", -3
        elif a < f:
            return "🟢 BUY GOLD BIAS - USD yếu hơn", 3

    if any(x in title_low for x in jobs_strong_bad_for_gold):
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

try:
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
    xml = requests.get(url, timeout=20).text

    soup = BeautifulSoup(xml, "xml")
    events = soup.find_all("event")

    message = "🔥 HIGH IMPACT USD - TIN ẢNH HƯỞNG VÀNG\n\n"
    count = 0
    total_score = 0

    for event in events:
        currency = event.find("country")
        impact = event.find("impact")
        title = event.find("title")
        date = event.find("date")
        time = event.find("time")
        forecast = event.find("forecast")
        previous = event.find("previous")
        actual = event.find("actual")

        currency = currency.text.strip() if currency else ""
        impact = impact.text.strip() if impact else ""
        title = title.text.strip() if title else ""
        date = date.text.strip() if date else ""
        time = time.text.strip() if time else ""
        forecast = forecast.text.strip() if forecast else "-"
        previous = previous.text.strip() if previous else "-"
        actual = actual.text.strip() if actual else "-"

        if currency == "USD" and impact == "High" and is_important(title):
            bias, score = gold_bias(title, actual, forecast)
            total_score += score

            message += f"🇺🇸 {date} {time} - USD time\n"
            message += f"{title}\n"
            message += "Impact: 🔴 High\n"
            message += f"Actual: {actual} | Forecast: {forecast} | Previous: {previous}\n"
            message += f"{bias}\n"
            message += f"Score: {score}\n\n"

            count += 1

        if count >= 12:
            break

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

except Exception as e:
    send_telegram(f"❌ ERROR\n{str(e)}")
