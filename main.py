import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"

JST = timezone(timedelta(hours=9))

USD_IMPORTANT = [
    "CPI", "PPI", "NFP", "Non-Farm", "Nonfarm",
    "FOMC", "Powell", "Fed", "Core PCE",
    "Unemployment", "Jobless Claims",
    "Retail Sales", "GDP", "ISM", "PMI"
]

def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    }, timeout=20)

def now_jst():
    return datetime.now(JST)

def mark_event(country, title, impact):
    t = title.upper()
    important = country == "USD" and any(k.upper() in t for k in USD_IMPORTANT)

    if impact == "High" or important:
        return "🔴"
    if impact == "Medium":
        return "🟡"
    return "⚪"

def gold_note(country, title, impact):
    if country != "USD":
        return ""

    t = title.upper()
    if impact == "High" or any(k.upper() in t for k in USD_IMPORTANT):
        return "🥇 XAUUSD: dễ biến động mạnh, tránh vào lệnh trước tin."
    return ""

def parse_ff_date(date_text, time_text):
    # ForexFactory XML thường là MM-DD-YYYY + giờ dạng 8:30am
    try:
        d = datetime.strptime(date_text, "%m-%d-%Y").date()
    except:
        return None

    if not time_text or time_text.lower() in ["all day", "tentative"]:
        return datetime(d.year, d.month, d.day, 0, 0, tzinfo=JST)

    try:
        tm = datetime.strptime(time_text.lower(), "%I:%M%p").time()
        return datetime(d.year, d.month, d.day, tm.hour, tm.minute, tzinfo=JST)
    except:
        return datetime(d.year, d.month, d.day, 0, 0, tzinfo=JST)

def load_events():
    r = requests.get(CALENDAR_URL, timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)

    events = []
    today = now_jst().date()

    for e in root.findall("event"):
        title = e.findtext("title", "").strip()
        country = e.findtext("country", "").strip()
        date_text = e.findtext("date", "").strip()
        time_text = e.findtext("time", "").strip()
        impact = e.findtext("impact", "").strip()
        forecast = e.findtext("forecast", "").strip()
        previous = e.findtext("previous", "").strip()
        actual = e.findtext("actual", "").strip()

        dt = parse_ff_date(date_text, time_text)
        if dt is None or dt.date() != today:
            continue

        events.append({
            "dt": dt,
            "time": time_text,
            "title": title,
            "country": country,
            "impact": impact,
            "forecast": forecast,
            "previous": previous,
            "actual": actual,
            "mark": mark_event(country, title, impact),
        })

    return sorted(events, key=lambda x: x["dt"])

def daily_report(events):
    today = now_jst().strftime("%Y-%m-%d")

    if not events:
        return f"""📅 <b>LỊCH TIN HÔM NAY</b>

Ngày: {today}

Hôm nay không có tin kinh tế trong lịch.
Nếu là cuối tuần thì sàn vàng nghỉ, bot vẫn hoạt động bình thường."""

    lines = [
        "📅 <b>LỊCH TIN KINH TẾ HÔM NAY</b>",
        f"Ngày: {today}",
        "",
        "Ký hiệu: 🔴 mạnh | 🟡 vừa | ⚪ nhẹ",
        ""
    ]

    for e in events:
        lines.append(f"{e['mark']} <b>{e['time']}</b> | {e['country']} | {e['title']}")
        lines.append(f"Actual: {e['actual'] or '-'} | Forecast: {e['forecast'] or '-'} | Previous: {e['previous'] or '-'}")
        note = gold_note(e["country"], e["title"], e["impact"])
        if note:
            lines.append(note)
        lines.append("")

    return "\n".join(lines)[:3900]

def warning_30m(events):
    now = now_jst()
    lines = []

    for e in events:
        diff = (e["dt"] - now).total_seconds() / 60
        if 0 <= diff <= 35 and e["mark"] == "🔴":
            lines.append(f"""🚨 <b>SẮP CÓ TIN ĐỎ</b>

Còn khoảng {int(diff)} phút

{e['country']} | {e['title']}
Giờ: {e['time']}
Forecast: {e['forecast'] or '-'}
Previous: {e['previous'] or '-'}

🥇 XAUUSD:
Tránh vào lệnh trước tin.
Chờ tin ra 5–15 phút rồi mới trade theo Sweep + CHOCH.""")

    return "\n\n".join(lines)

def actual_report(events):
    lines = []

    for e in events:
        if e["mark"] != "🔴":
            continue
        if not e["actual"] or not e["forecast"]:
            continue

        lines.append(f"""📊 <b>KẾT QUẢ TIN ĐỎ</b>

{e['country']} | {e['title']}
Actual: {e['actual']}
Forecast: {e['forecast']}
Previous: {e['previous'] or '-'}

🥇 XAUUSD:
So sánh Actual với Forecast rồi xem phản ứng nến M5/M15.
Nếu USD mạnh hơn dự báo → vàng dễ giảm.
Nếu USD yếu hơn dự báo → vàng dễ tăng.""")

    return "\n\n".join(lines)

def main():
    events = load_events()
    mode = os.getenv("MODE", "daily")

    if mode == "warning":
        msg = warning_30m(events)
        if msg:
            send(msg)
    elif mode == "actual":
        msg = actual_report(events)
        if msg:
            send(msg)
    else:
        send(daily_report(events))

if __name__ == "__main__":
    main()
