import os
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text})

try:
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
    xml = requests.get(url, timeout=20).text

    soup = BeautifulSoup(xml, "xml")
    events = soup.find_all("event")

    message = "🔥 HIGH IMPACT USD - TIN ẢNH HƯỞNG VÀNG\n\n"
    count = 0

    for event in events:
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

        if currency == "USD" and impact == "High":
            message += f"🇺🇸 {date} {time}\n"
            message += f"{title}\n"
            message += f"Impact: 🔴 High\n"
            message += f"Actual: {actual} | Forecast: {forecast} | Previous: {previous}\n\n"
            count += 1

        if count >= 10:
            break

    if count == 0:
        message += "⚠️ Tuần này chưa tìm thấy tin USD High Impact.\n"

    send_telegram(message)

except Exception as e:
    send_telegram(f"❌ ERROR\n{str(e)}")
