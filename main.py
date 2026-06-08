import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
MODE = os.getenv("MODE", "daily")

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
JST = timezone(timedelta(hours=9))

GOLD_COUNTRIES = ["USD", "EUR", "GBP", "JPY", "CNY", "AUD", "CAD", "CHF"]

USD_NEWS = [
    "CPI", "CORE CPI", "PPI", "CORE PCE", "PCE",
    "NFP", "NON-FARM", "NONFARM",
    "FOMC", "FED", "POWELL",
    "UNEMPLOYMENT", "JOBLESS CLAIMS",
    "RETAIL SALES", "GDP", "ISM", "PMI"
]

ASIA_NEWS = [
    "BOJ", "TOKYO CPI", "JAPAN CPI", "CPI",
    "CHINA", "CAIXIN", "MANUFACTURING PMI",
    "GDP", "RBA", "EMPLOYMENT"
]

EUROPE_NEWS = [
    "ECB", "LAGARDE", "EURO CPI", "GERMAN CPI",
    "BOE", "UK CPI", "GDP", "PMI"
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
    if country not in GOLD_COUNTRIES:
        return False

    title_upper = title.upper()

    if impact == "High":
        return True

    if country == "USD":
        return any(k in title_upper for k in USD_NEWS)

    if country in ["JPY", "CNY", "AUD"]:
        return any(k in title_upper for k in ASIA_NEWS)

    if country in ["EUR", "GBP", "CHF"]:
        return any(k in title_upper for k in EUROPE_NEWS)

    if country == "CAD":
        return "EMPLOYMENT" in title_upper or "GDP" in title_upper or "CPI" in title_upper

    return False

def impact_mark(impact, title, country):
    if is_gold_news(country, title, impact):
        return "🔴"
    if impact == "Medium":
        return "🟡"
    return "⚪"

def session_name(dt):
    h = dt.hour

    if 7 <= h < 16:
        return "🌏 Phiên Á"
    if 16 <= h < 21:
        return "🇬🇧 Phiên Âu"
    if 21 <= h or h < 2:
        return "🇺🇸 Phiên Mỹ"
    return "🌙 Thanh khoản yếu"

def gold_before_note(country, title):
    t = title.upper()

    if country == "USD":
        if any(k in t for k in SELL_GOLD_IF_HIGHER):
            return """📌 <b>Kịch bản XAUUSD</b>
Actual > Forecast → USD mạnh → SELL GOLD
Actual < Forecast → USD yếu → BUY GOLD"""

        if any(k in t for k in BUY_GOLD_IF_HIGHER):
            return """📌 <b>Kịch bản XAUUSD</b>
Actual > Forecast → USD yếu → BUY GOLD
Actual < Forecast → USD mạnh → SELL GOLD"""

        if "FOMC" in t or "FED" in t or "POWELL" in t:
            return """📌 <b>Kịch bản XAUUSD</b>
Fed hawkish / nói cứng → SELL GOLD
Fed dovish / nói mềm → BUY GOLD"""

    if country in ["JPY", "CNY", "AUD"]:
        return """📌 <b>Phiên Á</b>
Tin Á mạnh có thể làm vàng quét mạnh.
Ưu tiên chờ phản ứng giá, không vào trước tin."""

    if country in ["EUR", "GBP", "CHF"]:
        return """📌 <b>Phiên Âu</b>
Tin Âu mạnh có thể làm thị trường biến động trước phiên Mỹ.
Chờ sweep + CHOCH rồi mới vào."""

    if country == "CAD":
        return """📌 <b>Tin CAD</b>
Có thể ảnh hưởng USD gián tiếp.
Theo dõi phản ứng vàng trên M5/M15."""

    return "📌 XAUUSD: chờ tin ra, không vào lệnh trước tin."

def gold_after_result(country, title, actual, forecast):
    t = title.upper()
    a = to_float(actual)
    f = to_float(forecast)

    if country != "USD":
        return "🥇 XAUUSD: tin ngoài USD, ưu tiên xem phản ứng giá M5/M15."

    if a is None or f is None:
        return "🥇 XAUUSD: chưa đủ dữ liệu Actual/Forecast để kết luận."

    if any(k in t for k in SELL_GOLD_IF_HIGHER):
        if a > f:
            return "🥇 XAUUSD: Actual cao hơn Forecast → USD mạnh → ưu tiên SELL GOLD"
        if a < f:
            return "🥇 XAUUSD: Actual thấp hơn Forecast → USD yếu → ưu tiên BUY GOLD"
        return "🥇 XAUUSD: Actual bằng Forecast → chờ phản ứng giá."

    if any(k in t for k in BUY_GOLD_IF_HIGHER):
        if a > f:
            return "🥇 XAUUSD: thất nghiệp cao hơn dự báo → USD yếu → ưu tiên BUY GOLD"
        if a < f:
            return "🥇 XAUUSD: thất nghiệp thấp hơn dự báo → USD mạnh → ưu tiên SELL GOLD"
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
            "mark": impact_mark(impact, title, country),
            "session": session_name(dt)
        })

    return sorted(events, key=lambda x: x["dt"])

def daily_report(events):
    today = now_jst().strftime("%Y-%m-%d")

    if not events:
        return f"""📅 <b>TIN VÀNG HÔM NAY</b>

Ngày: {today}

Hôm nay chưa có tin lớn ảnh hưởng trực tiếp tới XAUUSD.
Nếu là cuối tuần thì sàn vàng nghỉ."""

    lines = [
        "🥇 <b>TIN VÀNG XAUUSD HÔM NAY</b>",
        f"Ngày: {today}",
        "",
        "🔴 Tin mạnh | 🟡 Tin vừa | ⚪ Tin nhẹ",
        ""
    ]

    current_session = ""

    for e in events:
        if e["session"] != current_session:
            current_session = e["session"]
            lines.append(f"<b>{current_session}</b>")

        lines.append(f"{e['mark']} <b>{e['time']}</b> | {e['country']} | {e['title']}")
        lines.append(f"Actual: {e['actual'] or '-'} | Forecast: {e['forecast'] or '-'} | Previous: {e['previous'] or '-'}")
        lines.append(gold_before_note(e["country"], e["title"]))
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

{e['session']}
{e['country']} | {e['title']}
Giờ: {e['time']}
Forecast: {e['forecast'] or '-'}
Previous: {e['previous'] or '-'}

{gold_before_note(e['country'], e['title'])}

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

{e['session']}
{e['country']} | {e['title']}
Actual: {e['actual']}
Forecast: {e['forecast'] or '-'}
Previous: {e['previous'] or '-'}

{gold_after_result(e['country'], e['title'], e['actual'], e['forecast'])}

⚠️ Không vào market ngay cây đầu tiên.
Chờ M5/M15 xác nhận hướng.""")

    return "\n\n".join(lines)

def main():
    try:
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

    except Exception as e:
        send(f"⚠️ Bot lỗi dữ liệu:\n{str(e)}")

if __name__ == "__main__":
    main()
