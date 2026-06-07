import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
MODE = os.getenv("MODE", "daily")

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
JST = timezone(timedelta(hours=9))

GOLD_NEWS = [
    "CPI", "CORE CPI", "PPI", "CORE PCE", "PCE",
    "NFP", "NON-FARM", "NONFARM",
    "FOMC", "FED", "POWELL",
    "UNEMPLOYMENT", "JOBLESS CLAIMS",
    "RETAIL SALES", "GDP", "ISM", "PMI"
]

SELL_GOLD_IF_HIGHER = [
    "CPI", "CORE CPI", "PPI", "CORE PCE", "PCE",
    "NFP", "NON-FARM", "NONFARM",
    "RETAIL SALES", "GDP", "ISM", "PMI"
]

BUY_GOLD_IF_HIGHER = [
    "UNEMPLOYMENT", "JOBLESS CLAIMS"
]

def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "HTML"
        },
        timeout=20
    )

def now_jst():
    return datetime.now(JST)

def to_float(x):
    if not x:
        return None
    x = x.replace("%", "").replace("K", "").replace("M", "").replace(",", "").strip()
    try:
        return float(x)
    except:
        return None

def parse_date(date_text, time_text):
    try:
        d = datetime.strptime(date_text, "%m-%d-%Y").date()
    except:
        return None

    if not time_text or time_text.lower() in ["all day", "tentative"]:
        return datetime(d.year, d.month, d.day, 0, 0, tzinfo=JST)

    try:
        t = datetime.strptime(time_text.lower(), "%I:%M%p").time()
        return datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=JST)
    except:
        return datetime(d.year, d.month, d.day, 0, 0, tzinfo=JST)

def is_gold_news(country, title, impact):
    if country != "USD":
        return False
    title_upper = title.upper()
    return impact == "High" or any(k in title_upper for k in GOLD_NEWS)

def impact_mark(impact, title, country):
    if is_gold_news(country, title, impact):
        return "🔴"
    if impact == "Medium":
        return "🟡"
    return "⚪"

def gold_before_note(title, forecast, previous):
    t = title.upper()

    if any(k in t for k in SELL_GOLD_IF_HIGHER):
        return f"""📌 <b>Kịch bản XAUUSD</b>
Nếu Actual > Forecast → USD mạnh → SELL GOLD
Nếu Actual < Forecast → USD yếu → BUY GOLD"""

    if any(k in t for k in BUY_GOLD_IF_HIGHER):
        return f"""📌 <b>Kịch bản XAUUSD</b>
Nếu Actual > Forecast → USD yếu → BUY GOLD
Nếu Actual < Forecast → USD mạnh → SELL GOLD"""

    if "FOMC" in t or "FED" in t or "POWELL" in t:
        return """📌 <b>Kịch bản XAUUSD</b>
Fed hawkish / nói cứng → SELL GOLD
Fed dovish / nói mềm → BUY GOLD"""

    return "📌 XAUUSD: chờ tin ra, không vào lệnh trước tin."

def gold_after_result(title, actual, forecast):
    t = title.upper()
    a = to_float(actual)
    f = to_float(forecast)

    if a is None or f is None:
        return "🥇 XAUUSD: chưa đủ dữ liệu Actual/Forecast để kết luận."

    if any(k in t for k in SELL_GOLD_IF_HIGHER):
        if a > f:
            return "🥇 XAUUSD: Actual cao hơn Forecast → USD mạnh → ưu tiên SELL GOLD"
        elif a < f:
            return "🥇 XAUUSD: Actual thấp hơn Forecast → USD yếu → ưu tiên BUY GOLD"
        else:
            return "🥇 XAUUSD: Actual bằng Forecast → chờ phản ứng giá."

    if any(k in t for k in BUY_GOLD_IF_HIGHER):
        if a > f:
            return "🥇 XAUUSD: thất nghiệp cao hơn dự báo → USD yếu → ưu tiên BUY GOLD"
        elif a < f:
            return "🥇 XAUUSD: thất nghiệp thấp hơn dự báo → USD mạnh → ưu tiên SELL GOLD"
        else:
            return "🥇 XAUUSD: Actual bằng Forecast → chờ phản ứng giá."

    return "🥇 XAUUSD: cần xem phản ứng nến M5/M15."

def load_events():
    r = requests.get(CALENDAR_URL, timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)

    today = now_jst().date()
    events = []

    for e in root.findall("event"):
        title = e.findtext("title", "").strip()
        country = e.findtext("country", "").strip()
        date_text = e.findtext("date", "").strip()
        time_text = e.findtext("time", "").strip()
        impact = e.findtext("impact", "").strip()
        forecast = e.findtext("forecast", "").strip()
        previous = e.findtext("previous", "").strip()
        actual = e.findtext("actual", "").strip()

        dt = parse_date(date_text, time_text)
        if dt is None or dt.date() != today:
            continue

        if not is_gold_news(country, title, impact):
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
            "mark": impact_mark(impact, title, country)
        })

    return sorted(events, key=lambda x: x["dt"])

def daily_report(events):
    today = now_jst().strftime("%Y-%m-%d")

    if not events:
        return f"""📅 <b>TIN VÀNG HÔM NAY</b>

Ngày: {today}

Hôm nay chưa có tin USD mạnh ảnh hưởng trực tiếp tới XAUUSD.
Nếu là cuối tuần thì sàn vàng nghỉ."""

    lines = [
        "🥇 <b>TIN VÀNG XAUUSD HÔM NAY</b>",
        f"Ngày: {today}",
        "",
        "🔴 Tin mạnh ảnh hưởng vàng",
        ""
    ]

    for e in events:
        lines.append(f"{e['mark']} <b>{e['time']}</b> | {e['country']} | {e['title']}")
        lines.append(f"Actual: {e['actual'] or '-'} | Forecast: {e['forecast'] or '-'} | Previous: {e['previous'] or '-'}")
        lines.append(gold_before_note(e["title"], e["forecast"], e["previous"]))
        lines.append("")

    return "\n".join(lines)[:3900]

def warning_report(events):
    now = now_jst()
    lines = []

    for e in events:
        diff = (e["dt"] - now).total_seconds() / 60

        if 0 <= diff <= 35:
            lines.append(f"""🚨 <b>SẮP CÓ TIN VÀNG</b>

Còn khoảng {int(diff)} phút

{e['country']} | {e['title']}
Giờ: {e['time']}
Forecast: {e['forecast'] or '-'}
Previous: {e['previous'] or '-'}

{gold_before_note(e['title'], e['forecast'], e['previous'])}

⚠️ Không vào lệnh trước tin.
Chờ tin ra 5–15 phút rồi xem Sweep + CHOCH.""")

    return "\n\n".join(lines)

def actual_report(events):
    now = now_jst()
    lines = []

    for e in events:
        diff = (now - e["dt"]).total_seconds() / 60

        if 0 <= diff <= 90 and e["actual"]:
            lines.append(f"""📊 <b>KẾT QUẢ TIN VÀNG</b>

{e['country']} | {e['title']}
Actual: {e['actual']}
Forecast: {e['forecast'] or '-'}
Previous: {e['previous'] or '-'}

{gold_after_result(e['title'], e['actual'], e['forecast'])}

⚠️ Không vào market ngay cây đầu tiên.
Chờ M5/M15 xác nhận hướng.""")

    return "\n\n".join(lines)

def main():
    events = load_events()

    if MODE == "warning":
        msg = warning_report(events)
        if msg:
            send(msg)

    elif MODE == "actual":
        msg = actual_report(events)
        if msg:
            send(msg)

    else:
        send(daily_report(events))

if __name__ == "__main__":
    main()
