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

    message = "🔥 TIN USD QUAN TRỌNG TUẦN NÀY\n\n"
    count = 0

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

        if currency == "USD":
            message += f"🇺🇸 {date} {time}\n"
            message += f"{title}\n"
            message += f"Impact: {impact}\n"
            message += f"Actual: {actual} | Forecast: {forecast} | Previous: {previous}\n\n"
            count += 1

        if count >= 10:
            break

    if count == 0:
        message += f"⚠️ Không tìm thấy tin USD.\nSố event đọc được: {len(events)}"

    send_telegram(message)

except Exception as e:
    send_telegram(f"❌ ERROR\n{str(e)}")
