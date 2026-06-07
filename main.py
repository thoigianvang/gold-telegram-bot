import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"

IMPORTANT_WORDS = [
    "CPI", "PPI", "NFP", "Non-Farm", "Nonfarm",
    "FOMC", "Fed", "Powell",
    "Unemployment", "Jobless Claims",
    "Core PCE", "Retail Sales",
    "GDP", "PMI", "ISM"
]

def send(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }, timeout=20)

def now_jst():
    return datetime.now(timezone(timedelta(hours=9)))

def is_important(title):
    title_upper = title.upper()
    return any(word.upper() in title_upper for word in IMPORTANT_WORDS)

def main():
    today = now_jst().date()

    r = requests.get(CALENDAR_URL, timeout=20)
    r.raise_for_status()

    root = ET.fromstring(r.content)

    events = []

    for event in root.findall("event"):
        title = event.findtext("title", "")
        country = event.findtext("country", "")
        date_text = event.findtext("date", "")
        time_text = event.findtext("time", "")
        impact = event.findtext("impact", "")
        forecast = event.findtext("forecast", "")
        previous = event.findtext("previous", "")

        if not title or not date_text:
            continue

        # ForexFactory XML thường dùng MM-DD-YYYY
        try:
            event_date = datetime.strptime(date_text, "%m-%d-%Y").date()
        except:
            continue

        if event_date != today:
            continue

        mark = "🔴" if impact == "High" or is_important(title) else "🟡" if impact == "Medium" else "⚪"

        events.append({
            "mark": mark,
            "time": time_text,
            "country": country,
            "title": title,
            "impact": impact,
            "forecast": forecast,
            "previous": previous,
        })

    if not events:
        msg = f"📅 <b>LỊCH TIN HÔM NAY</b>\n\nHôm nay chưa thấy tin kinh tế quan trọng trong lịch."
        send(msg)
        return

    lines = []
    lines.append("📅 <b>LỊCH TIN KINH TẾ HÔM NAY</b>")
    lines.append(f"⏰ Ngày: {today}")
    lines.append("")
    lines.append("🥇 <b>Chú ý XAUUSD:</b>")
    lines.append("🔴 Tin đỏ USD dễ làm vàng quét mạnh.")
    lines.append("")

    for e in events:
        lines.append(f"{e['mark']} <b>{e['time']}</b> | {e['country']} | {e['title']}")
        lines.append(f"Impact: {e['impact']} | Forecast: {e['forecast']} | Previous: {e['previous']}")
        lines.append("")

    msg = "\n".join(lines)

    # Telegram giới hạn tin nhắn, cắt nếu quá dài
    if len(msg) > 3800:
        msg = msg[:3800] + "\n\n...Tin quá dài, đã rút gọn."

    send(msg)

if __name__ == "__main__":
    main()
