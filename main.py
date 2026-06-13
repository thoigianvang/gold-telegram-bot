import os
import requests
from datetime import datetime
from bs4 import BeautifulSoup

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": text
        }
    )

try:
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"

    xml = requests.get(url, timeout=20).text

    soup = BeautifulSoup(xml, "xml")

    events = soup.find_all("event")

    message = "🔥 TIN USD QUAN TRỌNG TUẦN NÀY\n\n"

    count = 0

    for event in events:

        currency = event.currency.text if event.currency else ""

        impact = event.impact.text if event.impact else ""

        title = event.title.text if event.title else ""

        if currency == "USD":

            message += f"🇺🇸 {title}\n"
            message += f"Impact: {impact}\n\n"

            count += 1

            if count >= 10:
                break

    send_telegram(message)

except Exception as e:

    send_telegram(f"❌ ERROR\n{str(e)}")
