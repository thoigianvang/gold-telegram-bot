import os
import re
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
MODE = os.getenv("MODE", "daily")

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
JST = timezone(timedelta(hours=9))

# =====================================================
# CẤU HÌNH TIN ẢNH HƯỞNG VÀNG
# =====================================================

GOLD_COUNTRIES = ["USD", "EUR", "GBP", "JPY", "CNY", "AUD", "CAD", "CHF"]

# Tin USD cực mạnh với XAUUSD
USD_RED_NEWS = [
    "CPI", "CORE CPI",
    "PPI",
    "PCE", "CORE PCE",
    "NFP", "NON-FARM", "NONFARM",
    "FOMC",
    "FED INTEREST RATE",
    "FED RATE",
    "POWELL",
    "UNEMPLOYMENT RATE",
    "JOBLESS CLAIMS",
    "RETAIL SALES",
    "ISM MANUFACTURING",
    "ISM SERVICES"
]

# Tin vừa/khá mạnh
MEDIUM_GOLD_NEWS = [
    "GDP",
    "PMI",
    "ECB",
    "LAGARDE",
    "BOE",
    "BOJ",
    "RBA",
    "EMPLOYMENT",
    "MANUFACTURING",
    "SERVICES",
    "CONSUMER SENTIMENT",
    "CONFIDENCE"
]

# Tin mà Actual cao hơn Forecast thường làm USD mạnh -> vàng giảm
SELL_GOLD_IF_HIGHER = [
    "CPI", "CORE CPI",
    "PPI",
    "PCE", "CORE PCE",
    "NFP", "NON-FARM", "NONFARM",
    "RETAIL SALES",
    "GDP",
    "ISM",
    "PMI"
]

# Tin mà Actual cao hơn Forecast thường xấu cho USD -> vàng tăng
BUY_GOLD_IF_HIGHER = [
    "UNEMPLOYMENT RATE",
    "JOBLESS CLAIMS"
]

# =====================================================
# TELEGRAM
# =====================================================

def send(msg):
    if not msg:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    # Telegram limit khoảng 4096 ký tự
    chunks = [msg[i:i+3900] for i in range(0, len(msg), 3900)]

    for chunk in chunks:
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

# =====================================================
# XỬ LÝ SỐ
# =====================================================

def to_float(x):
    if not x:
        return None

    x = x.strip()
    x = x.replace("%", "")
    x = x.replace(",", "")

    multiplier = 1

    if x.upper().endswith("K"):
        multiplier = 1000
        x = x[:-1]

    elif x.upper().endswith("M"):
        multiplier = 1000000
        x = x[:-1]

    try:
        return float(x) * multiplier
    except:
        return None

# =====================================================
# GIỜ / PHIÊN
# =====================================================

def parse_date(date_text, time_text):
    try:
        d = datetime.strptime(date_text, "%m-%d-%Y").date()
    except:
        return None

    if not time_text:
        return datetime(d.year, d.month, d.day, 0, 0, tzinfo=JST)

    t_raw = time_text.strip().lower()

    if t_raw in ["all day", "tentative"]:
        return datetime(d.year, d.month, d.day, 0, 0, tzinfo=JST)

    try:
        t = datetime.strptime(t_raw, "%I:%M%p").time()
        return datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=JST)
    except:
        return datetime(d.year, d.month, d.day, 0, 0, tzinfo=JST)

def session_name(dt, country):
    h = dt.hour

    # Ưu tiên theo quốc gia trước
    if country in ["JPY", "CNY", "AUD"]:
        return "🌏 Phiên Á"

    if country in ["EUR", "GBP", "CHF"]:
        return "🇬🇧 Phiên Âu"

    if country in ["USD", "CAD"]:
        return "🇺🇸 Phiên Mỹ"

    # Nếu không rõ thì phân loại theo giờ Nhật
    if 6 <= h < 15:
        return "🌏 Phiên Á"
    if 15 <= h < 21:
        return "🇬🇧 Phiên Âu"
    if 21 <= h or h < 3:
        return "🇺🇸 Phiên Mỹ"

    return "🌙 Thanh khoản yếu"

# =====================================================
# PHÂN LOẠI TIN
# =====================================================

def has_keyword(title, keywords):
    t = title.upper()
    return any(k.upper() in t for k in keywords)

def is_gold_news(country, title, impact):
    if country not in GOLD_COUNTRIES:
        return False

    t = title.upper()

    # USD là trọng tâm vàng
    if country == "USD":
        if impact == "High":
            return True
        if has_keyword(t, USD_RED_NEWS):
            return True
        if has_keyword(t, MEDIUM_GOLD_NEWS):
            return True
        return False

    # Tin ngoài USD chỉ lấy tin high hoặc các tin chính
    if impact == "High":
        return True

    if country in ["JPY", "CNY", "AUD"]:
        return has_keyword(t, ["BOJ", "RBA", "CPI", "GDP", "PMI", "CAIXIN", "EMPLOYMENT"])

    if country in ["EUR", "GBP", "CHF"]:
        return has_keyword(t, ["ECB", "BOE", "CPI", "GDP", "PMI", "LAGARDE", "RATE"])

    if country == "CAD":
        return has_keyword(t, ["CPI", "GDP", "EMPLOYMENT", "RETAIL SALES"])

    return False

def event_strength(country, title, impact):
    t = title.upper()

    if country == "USD" and has_keyword(t, USD_RED_NEWS):
        return "🔴", "CỰC MẠNH"

    if country == "USD" and impact == "High":
        return "🔴", "CỰC MẠNH"

    if impact == "High":
        return "🟡", "MẠNH"

    if has_keyword(t, MEDIUM_GOLD_NEWS):
        return "🟡", "VỪA"

    return "⚪", "NHẸ"

# =====================================================
# NHẬN ĐỊNH VÀNG
# =====================================================

def gold_before_note(country, title):
    t = title.upper()

    if country == "USD":
        if has_keyword(t, SELL_GOLD_IF_HIGHER):
            return """📌 <b>Kịch bản XAUUSD</b>
Actual > Forecast → USD mạnh → SELL GOLD
Actual < Forecast → USD yếu → BUY GOLD"""

        if has_keyword(t, BUY_GOLD_IF_HIGHER):
            return """📌 <b>Kịch bản XAUUSD</b>
Actual > Forecast → USD yếu → BUY GOLD
Actual < Forecast → USD mạnh → SELL GOLD"""

        if has_keyword(t, ["FOMC", "FED", "POWELL"]):
            return """📌 <b>Kịch bản XAUUSD</b>
Fed hawkish / nói cứng → SELL GOLD
Fed dovish / nói mềm → BUY GOLD"""

        return """📌 <b>Kịch bản XAUUSD</b>
Tin USD mạnh hơn dự báo → thường SELL GOLD
Tin USD yếu hơn dự báo → thường BUY GOLD"""

    if country in ["JPY", "CNY", "AUD"]:
        return """📌 <b>Phiên Á</b>
Tin Á có thể làm vàng quét thanh khoản.
Không vào trước tin, chờ phản ứng giá."""

    if country in ["EUR", "GBP", "CHF"]:
        return """📌 <b>Phiên Âu</b>
Tin Âu có thể tạo sóng trước phiên Mỹ.
Chờ Sweep + CHOCH rồi mới vào."""

    if country == "CAD":
        return """📌 <b>Tin CAD</b>
Ảnh hưởng gián tiếp tới USD.
Theo dõi phản ứng XAUUSD trên M5/M15."""

    return "📌 XAUUSD: chờ tin ra, không vào lệnh trước tin."

def gold_after_result(country, title, actual, forecast):
    t = title.upper()
    a = to_float(actual)
    f = to_float(forecast)

    if country != "USD":
        return "🥇 XAUUSD: tin ngoài USD, ưu tiên xem phản ứng giá M5/M15."

    if a is None or f is None:
        return "🥇 XAUUSD: chưa đủ dữ liệu Actual/Forecast để kết luận."

    if has_keyword(t, SELL_GOLD_IF_HIGHER):
        if a > f:
            return "🥇 XAUUSD: Actual cao hơn Forecast → USD mạnh → ưu tiên SELL GOLD"
        if a < f:
            return "🥇 XAUUSD: Actual thấp hơn Forecast → USD yếu → ưu tiên BUY GOLD"
        return "🥇 XAUUSD: Actual bằng Forecast → chờ phản ứng giá."

    if has_keyword(t, BUY_GOLD_IF_HIGHER):
        if a > f:
            return "🥇 XAUUSD: thất nghiệp cao hơn dự báo → USD yếu → ưu tiên BUY GOLD"
        if a < f:
            return "🥇 XAUUSD: thất nghiệp thấp hơn dự báo → USD mạnh → ưu tiên SELL GOLD"
        return "🥇 XAUUSD: Actual bằng Forecast → chờ phản ứng giá."

    return "🥇 XAUUSD: cần xem phản ứng nến M5/M15."

# =====================================================
# LẤY DỮ LIỆU
# =====================================================

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
            "session": session_name(dt, country)
        })

    return sorted(events, key=lambda x: x["dt"])

# =====================================================
# BÁO CÁO HẰNG NGÀY
# =====================================================

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
        "🔴 Cực mạnh | 🟡 Mạnh/Vừa | ⚪ Nhẹ",
        ""
    ]

    current_session = ""

    for e in events:
        if e["session"] != current_session:
            current_session = e["session"]
            lines.append(f"<b>{current_session}</b>")

        lines.append(f"{e['mark']}
