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

USD_STRONG = [
    "CPI", "PPI", "PCE", "CORE PCE", "NFP", "NON-FARM", "NONFARM",
    "FOMC", "FED", "POWELL", "UNEMPLOYMENT", "JOBLESS CLAIMS",
    "RETAIL SALES", "ISM", "GDP", "PMI"
]

SELL_IF_HIGHER = [
    "CPI", "PPI", "PCE", "CORE PCE", "NFP", "NON-FARM", "NONFARM",
    "RETAIL SALES", "ISM", "GDP", "PMI"
]

BUY_IF_HIGHER = [
    "UNEMPLOYMENT", "JOBLESS CLAIMS"
]

OTHER_IMPORTANT = [
    "ECB", "BOE", "BOJ", "RBA", "PMI", "GDP", "CPI", "EMPLOYMENT",
    "LAGARDE", "RATE", "CAIXIN"
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
        return impact == "High" or has_word(title, USD_STRONG)

    if impact == "High":
        return True

    return has_word(title, OTHER_IMPORTANT)


def strength(country, title, impact):
    if country == "USD" and (impact == "High" or has_word(title, USD_STRONG)):
        return "🔴", "CỰC MẠNH"

    if impact == "High":
        return "🟡", "MẠNH"

    return "🟡", "VỪA"


def before_note(country, title):
    if country == "USD":
        if has_word(title, SELL_IF_HIGHER):
            return (
                "📌 <b>Kịch bản XAUUSD</b>\n"
                "Actual &gt; Forecast → USD mạnh → SELL GOLD\n"
                "Actual &lt; Forecast → USD yếu → BUY GOLD"
            )

        if has_word(title, BUY_IF_HIGHER):
            return (
                "📌 <b>Kịch bản XAUUSD</b>\n"
                "Actual &gt; Forecast → USD yếu → BUY GOLD\n"
                "Actual &lt; Forecast → USD mạnh → SELL GOLD"
            )

        if has_word(title, ["FOMC", "FED", "POWELL"]):
            return (
                "📌 <b>Kịch bản XAUUSD</b>\n"
                "Fed hawkish → SELL GOLD\n"
                "Fed dovish → BUY GOLD"
            )

    if country in ["JPY", "CNY", "AUD"]:
        return "📌 <b>Phiên Á</b>\nTin Á có thể làm vàng quét mạnh. Chờ phản ứng giá."

    if country in ["EUR", "GBP", "CHF"]:
        return "📌 <b>Phiên Âu</b>\nTin Âu có thể tạo sóng trước phiên Mỹ."

    return "📌 Chờ tin ra, không vào lệnh trước tin."


def after_result(country, title, actual, forecast):
    if country != "USD":
        return "🥇 Tin ngoài USD: ưu tiên xem phản ứng giá M5/M15."

    a = to_float(actual)
    f = to_float(forecast)

    if a is None or f is None:
        return "🥇 Chưa đủ dữ liệu Actual/Forecast để kết luận."

    if has_word(title, SELL_IF_HIGHER):
        if a > f:
            return "🥇 Actual cao hơn Forecast → USD mạnh → ưu tiên SELL GOLD"
        if a < f:
            return "🥇 Actual thấp hơn Forecast → USD yếu → ưu tiên BUY GOLD"
        return "🥇 Actual bằng Forecast → chờ phản ứng giá."

    if has_word(title, BUY_IF_HIGHER):
        if a > f:
            return "🥇 Thất nghiệp cao hơn dự báo → USD yếu → ưu tiên BUY GOLD"
        if a < f:
            return "🥇 Thất nghiệp thấp hơn dự báo → USD mạnh → ưu tiên SELL GOLD"
        return "🥇 Actual bằng Forecast → chờ phản ứng giá."

    return "🥇 Cần xem phản ứng nến M5/M15."


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
        "🔴 Cực mạnh | 🟡 Mạnh/Vừa",
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

        if 0 <= diff <= 35:
            lines.append(
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
                "Chờ tin ra 5–15 phút rồi xem Sweep + CHOCH."
            )

    return "\n\n".join(lines)


def actual_report(events):
    now = now_jst()
    lines = []

    for e in events:
        diff = (now - e["dt"]).total_seconds() / 60

        if 0 <= diff <= 90 and e["actual"]:
            lines.append(
                "📊 <b>KẾT QUẢ TIN VÀNG</b>\n\n"
                f"{safe(e['session'])}\n"
                f"{e['mark']} {safe(e['country'])} | {safe(e['title'])}\n"
                f"Mức độ: {safe(e['level'])}\n\n"
                f"Actual: {safe(e['actual'])}\n"
                f"Forecast: {safe(e['forecast'])}\n"
                f"Previous: {safe(e['previous'])}\n\n"
                f"{after_result(e['country'], e['title'], e['actual'], e['forecast'])}\n\n"
                "⚠️ Không vào market ngay cây đầu tiên.\n"
                "Chờ M5/M15 xác nhận hướng."
            )

    return "\n\n".join(lines)


def main():
    try:
        send("✅ Schedule test OK")
        print("MODE:", MODE)
        print("TIME JST:", now_jst().strftime("%Y-%m-%d %H:%M:%S"))

        events = load_events()

        if MODE == "warning":
            msg = warning_report(events)
            if msg:
                send(msg)
            else:
                print("No warning message")

        elif MODE == "actual":
            msg = actual_report(events)
            if msg:
                send(msg)
            else:
                print("No actual message")

        else:
            msg = daily_report(events)
            send(msg)

    except Exception as e:
        print("BOT ERROR:", str(e))
        send(f"⚠️ Bot lỗi dữ liệu:\n{safe(str(e))}")
        raise


if __name__ == "__main__":
    main()
