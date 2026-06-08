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

USD_SUPER = [
    "CPI", "CORE CPI", "PCE", "CORE PCE", "PPI",
    "NFP", "NON-FARM", "NONFARM",
    "FOMC", "FED", "POWELL",
    "UNEMPLOYMENT", "JOBLESS CLAIMS"
]

USD_MEDIUM = [
    "RETAIL SALES", "GDP", "ISM", "PMI",
    "CONSUMER SENTIMENT", "CONFIDENCE"
]

OTHER_IMPORTANT = [
    "ECB", "BOE", "BOJ", "RBA",
    "CPI", "GDP", "PMI", "RATE",
    "EMPLOYMENT", "LAGARDE", "CAIXIN"
]

SELL_IF_HIGHER = [
    "CPI", "CORE CPI", "PCE", "CORE PCE", "PPI",
    "NFP", "NON-FARM", "NONFARM",
    "RETAIL SALES", "GDP", "ISM", "PMI"
]

BUY_IF_HIGHER = [
    "UNEMPLOYMENT", "JOBLESS CLAIMS"
]


def now_jst():
    return datetime.now(JST)


def safe(x):
    return escape(str(x)) if x else "-"


def has_word(text, words):
    text = text.upper()
    return any(w.upper() in text for w in words)


def send(msg):
    if not msg:
        print("NO MESSAGE")
        return

    if not BOT_TOKEN:
        raise Exception("BOT_TOKEN is missing")

    if not CHAT_ID:
        raise Exception("CHAT_ID is missing")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    for i in range(0, len(msg), 3900):
        part = msg[i:i + 3900]
        r = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": part,
                "parse_mode": "HTML"
            },
            timeout=20
        )
        print("Telegram:", r.status_code, r.text)
        r.raise_for_status()


def to_float(x):
    if not x:
        return None

    x = x.strip().replace("%", "").replace(",", "")
    multi = 1

    if x.upper().endswith("K"):
        multi = 1000
        x = x[:-1]
    elif x.upper().endswith("M"):
        multi = 1000000
        x = x[:-1]

    try:
        return float(x) * multi
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
        return impact == "High" or has_word(title, USD_SUPER) or has_word(title, USD_MEDIUM)

    if impact == "High":
        return True

    return has_word(title, OTHER_IMPORTANT)


def strength(country, title, impact):
    if country == "USD" and (impact == "High" or has_word(title, USD_SUPER)):
        return "🔴", "RẤT MẠNH"

    if country == "USD" and has_word(title, USD_MEDIUM):
        return "🟡", "MẠNH"

    if impact == "High":
        return "🟡", "TRUNG BÌNH"

    return "⚪", "NHẸ"


def before_note(country, title):
    if country == "USD":
        if has_word(title, SELL_IF_HIGHER):
            return (
                "📌 <b>KỊCH BẢN XAUUSD</b>\n"
                "Actual &gt; Forecast → USD mạnh → SELL GOLD\n"
                "Actual &lt; Forecast → USD yếu → BUY GOLD"
            )

        if has_word(title, BUY_IF_HIGHER):
            return (
                "📌 <b>KỊCH BẢN XAUUSD</b>\n"
                "Actual &gt; Forecast → USD yếu → BUY GOLD\n"
                "Actual &lt; Forecast → USD mạnh → SELL GOLD"
            )

        if has_word(title, ["FOMC", "FED", "POWELL"]):
            return (
                "📌 <b>KỊCH BẢN XAUUSD</b>\n"
                "Fed hawkish / nói cứng → SELL GOLD\n"
                "Fed dovish / nói mềm → BUY GOLD"
            )

    if country in ["JPY", "CNY", "AUD"]:
        return (
            "📌 <b>PHIÊN Á</b>\n"
            "Tin này ảnh hưởng gián tiếp tới vàng.\n"
            "Ưu tiên chờ phản ứng giá, không vào trước tin."
        )

    if country in ["EUR", "GBP", "CHF"]:
        return (
            "📌 <b>PHIÊN ÂU</b>\n"
            "Tin Âu có thể làm USD biến động gián tiếp.\n"
            "Chờ Sweep + CHOCH rồi mới vào."
        )

    return "📌 Chờ tin ra, không vào lệnh trước tin."


def after_result(country, title, actual, forecast):
    a = to_float(actual)
    f = to_float(forecast)

    if country != "USD":
        return (
            "📌 Tác động: GIÁN TIẾP\n\n"
            "🥇 XAUUSD:\n"
            "Ưu tiên chờ phản ứng giá M5/M15.\n"
            "Không nên BUY/SELL chỉ vì tin này."
        )

    if a is None or f is None:
        return (
            "📌 Chưa đủ dữ liệu Actual/Forecast.\n\n"
            "🥇 XAUUSD:\n"
            "Chờ phản ứng giá."
        )

    if has_word(title, SELL_IF_HIGHER):
        if a > f:
            return (
                "📈 Dữ liệu mạnh hơn dự báo\n\n"
                "💵 USD mạnh\n\n"
                "🥇 XAUUSD:\n"
                "Ưu tiên SELL GOLD"
            )
        if a < f:
            return (
                "📉 Dữ liệu yếu hơn dự báo\n\n"
                "💵 USD yếu\n\n"
                "🥇 XAUUSD:\n"
                "Ưu tiên BUY GOLD"
            )
        return "Actual bằng Forecast → chờ phản ứng giá."

    if has_word(title, BUY_IF_HIGHER):
        if a > f:
            return (
                "📉 Thất nghiệp cao hơn dự báo\n\n"
                "💵 USD yếu\n\n"
                "🥇 XAUUSD:\n"
                "Ưu tiên BUY GOLD"
            )
        if a < f:
            return (
                "📈 Thất nghiệp thấp hơn dự báo\n\n"
                "💵 USD mạnh\n\n"
                "🥇 XAUUSD:\n"
                "Ưu tiên SELL GOLD"
            )
        return "Actual bằng Forecast → chờ phản ứng giá."

    return "🥇 XAUUSD: cần xem phản ứng nến M5/M15."


def load_events():
    r = requests.get(CALENDAR_URL, timeout=20)
    print("Calendar:", r.status_code)
    r.raise_for_status()

    root = ET.fromstring(r.content)
    today = now_jst().date()
    events = []

    for item in root.findall("event"):
        title = item.findtext("title", "").strip()
        country = item.findtext("country", "").strip()
        date_text = item.findtext("date", "").strip()
        time_text = item.findtext("time", "").strip()
        impact = item.findtext("impact", "").strip()
        forecast = item.findtext("forecast", "").strip()
        previous = item.findtext("previous", "").strip()
        actual = item.findtext("actual", "").strip()

        dt = parse_date(date_text, time_text)

        if dt is None:
            continue

        if dt.date() != today:
            continue

        if not is_gold_news(country, title, impact):
            continue

        mark, level = strength(country, title, impact)

        events.append({
            "dt": dt,
            "time": time_text,
            "title": title,
            "country": country,
            "forecast": forecast,
            "previous": previous,
            "actual": actual,
            "mark": mark,
            "level": level,
            "session": session_name(country, dt)
        })

    print("Events found:", len(events))
    return sorted(events, key=lambda x: x["dt"])


def daily_report(events):
    today = now_jst().strftime("%Y-%m-%d")

    if not events:
        return (
            "📅 <b>TIN VÀNG HÔM NAY</b>\n\n"
            f"Ngày: {today}\n\n"
            "Hôm nay chưa có tin lớn ảnh hưởng trực tiếp tới XAUUSD.\n"
            "Nếu là cuối tuần thì sàn vàng nghỉ."
        )

    lines = [
        "🥇 <b>TIN VÀNG XAUUSD HÔM NAY</b>",
        f"Ngày: {today}",
        "",
        "🔴 Rất mạnh | 🟡 Mạnh/Trung bình | ⚪ Nhẹ",
        ""
    ]

    current_session = ""

    for e in events:
        if e["session"] != current_session:
            current_session = e["session"]
            lines.append(f"<b>{current_session}</b>")

        lines.append(f"{e['mark']} <b>{safe(e['time'])}</b> | {safe(e['country'])} | {safe(e['title'])}")
        lines.append(f"Mức độ: {safe(e['level'])}")
        lines.append(f"Actual: {safe(e['actual'])} | Forecast: {safe(e['forecast'])} | Previous: {safe(e['previous'])}")
        lines.append(before_note(e["country"], e["title"]))
        lines.append("")

    return "\n".join(lines)

def warning_report(events):
    now = now_jst()
    lines = []

    for e in events:
        diff = (e["dt"] - now).total_seconds() / 60

        if 0 <= diff <= 35 and e["mark"] in ["🔴", "🟡"]:
            text = (
                "🚨 <b>SẮP CÓ TIN VÀNG</b>\n\n"
                f"Còn khoảng {int(diff)} phút\n\n"
                f"{safe(e['session'])}\n"
                f"{e['mark']} {safe(e['country'])} | {safe(e['title'])}\n"
                f"Mức độ: {safe(e['level'])}\n"
                f"Giờ: {safe(e['time'])}\n"
                f"Forecast: {safe(e['forecast'])}\n"
                f"Previous: {safe(e['previous'])}\n\n"
                f"{before_note(e['country'], e['title'])}\n\n"
                "⚠️ Không vào lệnh trước tin.\n"
                "Chờ tin ra 5-15 phút rồi xem Sweep + CHOCH."
            )
            lines.append(text)

    return "\n\n".join(lines)
