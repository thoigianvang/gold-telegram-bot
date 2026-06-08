import os
import requests
import xml.etree.ElementTree as ET
from html import escape
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
MODE = os.getenv("MODE", "daily")

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
JST = timezone(timedelta(hours=9))

GOLD_COUNTRIES = ["USD", "EUR", "GBP", "JPY", "CNY", "AUD", "CAD", "CHF"]

USD_RED_NEWS = [
    "CPI", "CORE CPI", "PPI", "PCE", "CORE PCE",
    "NFP", "NON-FARM", "NONFARM",
    "FOMC", "FED", "POWELL",
    "UNEMPLOYMENT", "JOBLESS CLAIMS",
    "RETAIL SALES", "ISM", "GDP"
]

MEDIUM_GOLD_NEWS = [
    "PMI", "ECB", "BOE", "BOJ", "RBA",
    "LAGARDE", "EMPLOYMENT", "MANUFACTURING",
    "SERVICES", "CONSUMER SENTIMENT", "CONFIDENCE"
]

SELL_GOLD_IF_HIGHER = [
    "CPI", "CORE CPI", "PPI", "PCE", "CORE PCE",
    "NFP", "NON-FARM", "NONFARM",
    "RETAIL SALES", "GDP", "ISM", "PMI"
]

BUY_GOLD_IF_HIGHER = [
    "UNEMPLOYMENT", "JOBLESS CLAIMS"
]

def send(msg):
    if not msg:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    for i in range(0, len(msg), 3900):
        chunk = msg[i:i + 3900]
        requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": chunk,
                "parse_mode": "HTML"
            },
            timeout=20
        )

def now_jst():
    return datetime.now(JST)

def safe(x):
    return escape(str(x)) if x else "-"

def has_keyword(title, words):
    t = title.upper()
    return any(w.upper() in t for w in words)

def to_float(x):
    if not x:
        return None

    x = x.strip().replace("%", "").replace(",", "")
    multiplier = 1

    if x.upper().endswith("K"):
        multiplier = 1000
        x = x[:-1]

    if x.upper().endswith("M"):
        multiplier = 1000000
        x = x[:-1]

    try:
        return float(x) * multiplier
    except:
        return None

def parse_date(date_text, time_text):
    try:
        d = datetime.strptime(date_text, "%m-%d-%Y").date()
    except:
        return None

    if not time_text:
        return datetime(d.year, d.month, d.day, 0, 0, tzinfo=JST)

    raw = time_text.strip().lower()

    if raw in ["all day", "tentative"]:
        return datetime(d.year, d.month, d.day, 0, 0, tzinfo=JST)

    try:
        t = datetime.strptime(raw, "%I:%M%p").time()
        return datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=JST)
    except:
        return datetime(d.year, d.month, d.day, 0, 0, tzinfo=JST)

def session_name(country, dt):
    if country in ["JPY", "CNY", "AUD"]:
        return "🌏 Phiên Á"

    if country in ["EUR", "GBP", "CHF"]:
        return "🇬🇧 Phiên Âu"

    if country in ["USD", "CAD"]:
        return "🇺🇸 Phiên Mỹ"

    h = dt.hour

    if 6 <= h < 15:
        return "🌏 Phiên Á"
    if 15 <= h < 21:
        return "🇬🇧 Phiên Âu"
    if h >= 21 or h < 3:
        return "🇺🇸 Phiên Mỹ"

    return "🌙 Thanh khoản yếu"

def is_gold_news(country, title, impact):
    if country not in GOLD_COUNTRIES:
        return False

    if country == "USD":
        return impact == "High" or has_keyword(title, USD_RED_NEWS) or has_keyword(title, MEDIUM_GOLD_NEWS)

    if impact == "High":
        return True

    if country in ["JPY", "CNY", "AUD"]:
        return has_keyword(title, ["BOJ", "RBA", "CPI", "GDP", "PMI", "CAIXIN", "EMPLOYMENT"])

    if country in ["EUR", "GBP", "CHF"]:
        return has_keyword(title, ["ECB", "BOE", "CPI", "GDP", "PMI", "LAGARDE", "RATE"])

    if country == "CAD":
        return has_keyword(title, ["CPI", "GDP", "EMPLOYMENT", "RETAIL SALES"])

    return False

def event_strength(country, title, impact):
    if country == "USD" and (impact == "High" or has_keyword(title, USD_RED_NEWS)):
        return "🔴", "CỰC MẠNH"

    if impact == "High":
        return "🟡", "MẠNH"

    if has_keyword(title, MEDIUM_GOLD_NEWS):
        return "🟡", "VỪA"

    return "⚪", "NHẸ"

def gold_before_note(country, title):
    if country == "USD":
        if has_keyword(title, SELL_GOLD_IF_HIGHER):
            return "📌 <b>Kịch bản XAUUSD</b>\nActual &gt; Forecast → USD mạnh → SELL GOLD\nActual &lt; Forecast → USD yếu → BUY GOLD"

        if has_keyword(title, BUY_GOLD_IF_HIGHER):
            return "📌 <b>Kịch bản XAUUSD</b>\nActual &gt; Forecast → USD yếu → BUY GOLD\nActual &lt; Forecast → USD mạnh → SELL GOLD"

        if has_keyword(title, ["FOMC", "FED", "POWELL"]):
            return "📌 <b>Kịch bản XAUUSD</b>\nFed hawkish / nói cứng → SELL GOLD\nFed dovish / nói mềm → BUY GOLD"

        return "📌 Tin USD mạnh hơn dự báo → vàng dễ giảm\nTin USD yếu hơn dự báo → vàng dễ tăng"

    if country in ["JPY", "CNY", "AUD"]:
        return "📌 <b>Phiên Á</b>\nTin Á có thể làm vàng quét thanh khoản.\nKhông vào trước tin, chờ phản ứng giá."

    if country in ["EUR", "GBP", "CHF"]:
        return "📌 <b>Phiên Âu</b>\nTin Âu có thể tạo sóng trước phiên Mỹ.\nChờ Sweep + CHOCH rồi mới vào."

    if country == "CAD":
        return "📌 <b>Tin CAD</b>\nẢnh hưởng gián tiếp tới USD.\nTheo dõi XAUUSD trên M5/M15."

    return "📌 XAUUSD: chờ tin ra, không vào lệnh trước tin."

def gold_after_result(country, title, actual, forecast):
    a = to_float(actual)
    f = to_float(forecast)

    if country != "USD":
        return "🥇 XAUUSD: tin ngoài USD, ưu tiên xem phản ứng giá M5/M15."

    if a is None or f is None:
        return "🥇 XAUUSD: chưa đủ dữ liệu Actual/Forecast để kết luận."

    if has_keyword(title, SELL_GOLD_IF_HIGHER):
        if a > f:
            return "🥇 XAUUSD: Actual cao hơn Forecast → USD mạnh → ưu tiên SELL GOLD"
        if a < f:
            return "🥇 XAUUSD: Actual thấp hơn Forecast → USD yếu → ưu tiên BUY GOLD"
        return "🥇 XAUUSD: Actual bằng Forecast → chờ phản ứng giá."

    if has_keyword(title, BUY_GOLD_IF_HIGHER):
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

        if dt is None:
            continue

        if dt.date() != today:
            continue

        if not is_gold_news(country, title, impact):
            continue

        mark, strength = event_strength(country, title, impact)

        events.append({
            "dt": dt,
            "time": time_text,
            "title": title,
            "country": country,
            "impact": impact,
            "forecast": forecast,
            "previous": previous,
            "actual": actual,
            "mark": mark,
            "strength": strength,
            "session": session_name(country, dt)
        })

    return sorted(events, key=lambda x: x["dt"])

def daily_report(events):
    today = now_jst().strftime("%Y-%m-%d")

    if not events:
        return f"📅 <b>TIN VÀNG HÔM NAY</b>\n\nNgày: {today}\n\nHôm nay chưa có tin lớn ảnh hưởng trực tiếp tới XAUUSD.\nNếu là cuối tuần thì sàn vàng nghỉ."

    lines = []
    lines.append("🥇 <b>TIN VÀNG XAUUSD HÔM NAY</b>")
    lines.append(f"Ngày: {today}")
    lines.append("")
    lines.append("🔴 Cực mạnh | 🟡 Mạnh/Vừa | ⚪ Nhẹ")
    lines.append("")

    current_session = ""

    for e in events:
        if e["session"] != current_session:
            current_session = e["session"]
            lines.append(f"<b>{current_session}</b>")

        lines.append(f"{e['mark']} <b>{safe(e['time'])}</b> | {safe(e['country'])} | {safe(e['title'])}")
        lines.append(f"Mức độ: {safe(e['strength'])}")
        lines.append(f"Actual: {safe(e['actual'])} | Forecast: {safe(e['forecast'])} | Previous: {safe(e['previous'])}")
        lines.append(gold_before_note(e["country"], e["title"]))
        lines.append("")

    return "\n".join(lines)

def warning_report(events):
    now = now_jst()
    lines = []

    for e in events:
        diff = (e["dt"] - now).total_seconds() / 60

        if 0 <= diff <= 35 and e["mark"] in ["🔴", "🟡"]:
            lines.append("🚨 <b>SẮP CÓ TIN VÀNG</b>")
            lines.append("")
            lines.append(f"Còn khoảng {int(diff)} phút")
            lines.append("")
            lines.append(f"{safe(e['session'])}")
            lines.append(f"{e['mark']} {safe(e['country'])} | {safe(e['title'])}")
            lines.append(f"Mức độ: {safe(e['strength'])}")
            lines.append(f"Giờ: {safe(e['time'])}")
            lines.append(f"Forecast: {safe(e['forecast'])}")
            lines.append(f"Previous: {safe(e['previous'])}")
            lines.append("")
            lines.append(gold_before_note(e["country"], e["title"]))
            lines.append("")
            lines.append("⚠️ Không vào lệnh trước tin.")
            lines.append("Chờ tin ra 5–15 phút rồi xem Sweep + CHOCH.")
            lines.append("")

    return "\n".join(lines)

def actual_report(events):
    now = now_jst()
    lines = []

    for e in events:
        diff = (now - e["dt"]).total_seconds() / 60

        if 0 <= diff <= 90 and e["actual"] and e["mark"] in ["🔴", "🟡"]:
            lines.append("📊 <b>KẾT QUẢ TIN VÀNG</b>")
            lines.append("")
            lines.append(f"{safe(e['session'])}")
            li
