import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from zoneinfo import ZoneInfo

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
MODE = os.getenv("MODE", "daily")

URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
STATE_FILE = "sent.json"

NY = ZoneInfo("America/New_York")
JST = ZoneInfo("Asia/Tokyo")

IMPORTANT = [
    "CPI", "Core CPI",
    "PPI", "Core PPI",
    "Non-Farm", "Nonfarm", "NFP",
    "FOMC", "Federal Funds", "Interest Rate",
    "Powell",
    "Unemployment",
    "Retail Sales",
    "GDP",
    "ISM",
    "PMI",
    "JOLTS",
    "ADP",
]

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def already_sent(state, key):
    return state.get(key) is True

def mark_sent(state, key):
    state[key] = True

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Missing BOT_TOKEN or CHAT_ID")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=20,
    )

    print("TELEGRAM:", r.status_code, r.text)

    if r.status_code != 200:
        raise RuntimeError(f"Telegram send failed: {r.status_code} {r.text}")

def is_important(title):
    title_l = title.lower()
    return any(k.lower() in title_l for k in IMPORTANT)

def clean_value(v):
    if not v:
        return "-"
    v = v.strip()
    return v if v else "-"

def to_number(v):
    if not v or v == "-":
        return None

    try:
        x = (
            v.replace("%", "")
             .replace(",", "")
             .replace("K", "")
             .replace("M", "")
             .replace("B", "")
             .strip()
        )
        return float(x)
    except Exception:
        return None

def parse_event_time(date_str, time_str):
    if not date_str or not time_str or time_str.lower() in ["all day", "tentative"]:
        return None

    formats = [
        "%m-%d-%Y %I:%M%p",
        "%m-%d-%Y %I:%M %p",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", fmt)
            return dt.replace(tzinfo=NY).astimezone(JST)
        except Exception:
            pass

    return None

def event_key(e):
    safe_title = e["title"].replace(" ", "_").replace("/", "_")
    return f"{e['date']}_{e['time']}_{safe_title}"

def gold_bias(title, actual, forecast):
    a = to_number(actual)
    f = to_number(forecast)

    if a is None or f is None:
        return "⏳ Chưa có Actual", 0

    t = title.lower()

    inflation = [
        "cpi", "ppi", "retail sales",
        "interest rate", "federal funds",
        "gdp", "ism", "pmi",
    ]

    jobs = [
        "non-farm", "nonfarm", "nfp",
        "adp", "jolts",
    ]

    if any(x in t for x in inflation):
        if a > f:
            return "🔴 SELL GOLD - USD mạnh hơn dự báo", -3
        if a < f:
            return "🟢 BUY GOLD - USD yếu hơn dự báo", 3

    if any(x in t for x in jobs):
        if a > f:
            return "🔴 SELL GOLD - dữ liệu việc làm mạnh", -3
        if a < f:
            return "🟢 BUY GOLD - dữ liệu việc làm yếu", 3

    if "unemployment" in t:
        if a > f:
            return "🟢 BUY GOLD - thất nghiệp cao hơn dự báo", 2
        if a < f:
            return "🔴 SELL GOLD - thất nghiệp thấp hơn dự báo", -2

    return "⚪ WAIT / NO TRADE", 0

def get_events():
    r = requests.get(URL, timeout=20)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "xml")
    events = []

    for e in soup.find_all("event"):
        country = clean_value(e.find("country").text if e.find("country") else "")
        impact = clean_value(e.find("impact").text if e.find("impact") else "")
        title = clean_value(e.find("title").text if e.find("title") else "")
        date = clean_value(e.find("date").text if e.find("date") else "")
        time = clean_value(e.find("time").text if e.find("time") else "")
        forecast = clean_value(e.find("forecast").text if e.find("forecast") else "-")
        previous = clean_value(e.find("previous").text if e.find("previous") else "-")
        actual = clean_value(e.find("actual").text if e.find("actual") else "-")

        jst_time = parse_event_time(date, time)

        if country == "USD" and impact == "High" and is_important(title):
            events.append({
                "title": title,
                "date": date,
                "time": time,
                "forecast": forecast,
                "previous": previous,
                "actual": actual,
                "jst": jst_time,
            })

    events.sort(key=lambda x: x["jst"] or datetime.max.replace(tzinfo=JST))
    return events

def today_and_next_events(events):
    now = datetime.now(JST)
    result = []

    for e in events:
        if not e["jst"]:
            continue

        diff = (e["jst"] - now).total_seconds()

        # Từ 6 tiếng trước tới 3 ngày tới
        if -6 * 3600 <= diff <= 3 * 86400:
            result.append(e)

    return result

def daily_report(events, state, force=False):
    today_key = f"daily_{datetime.now(JST).strftime('%Y-%m-%d')}"

    if not force and already_sent(state, today_key):
        print("Daily report already sent.")
        return

    selected = today_and_next_events(events)

    msg = "🔥 HIGH IMPACT USD - TIN ẢNH HƯỞNG VÀNG\n\n"

    if not selected:
        no_news_key = f"no_news_{datetime.now(JST).strftime('%Y-%m-%d')}"

        if not force and already_sent(state, no_news_key):
            print("No-news message already sent.")
            return

        msg += "⚪ Hiện chưa có tin USD High Impact quan trọng.\n"
        msg += "Không nên ép lệnh theo tin.\n\n"
        msg += f"🕒 Update: {datetime.now(JST).strftime('%m-%d %H:%M JST')}"

        send_telegram(msg)
        mark_sent(state, no_news_key)
        mark_sent(state, today_key)
        return

    total = 0

    for e in selected:
        bias, score = gold_bias(e["title"], e["actual"], e["forecast"])
        total += score

        msg += f"🇺🇸 {e['jst'].strftime('%m-%d %H:%M JST')}\n"
        msg += f"{e['title']}\n"
        msg += f"Actual: {e['actual']} | Forecast: {e['forecast']} | Previous: {e['previous']}\n"
        msg += f"{bias}\n"
        msg += f"Score: {score}\n\n"

    msg += "----------------------\n"
    msg += f"📊 Tổng Gold Score: {total}\n"

    if total >= 6:
        msg += "🟢 Kết luận: BUY GOLD BIAS mạnh"
    elif total <= -6:
        msg += "🔴 Kết luận: SELL GOLD BIAS mạnh"
    else:
        msg += "⚪ Kết luận: WAIT / NO TRADE"

    send_telegram(msg)
    mark_sent(state, today_key)

def check_events(events, state):
    now = datetime.now(JST)
    sent_any = False

    for e in events:
        if not e["jst"]:
            continue

        minutes = (e["jst"] - now).total_seconds() / 60
        key_base = event_key(e)

        # Cảnh báo 30 phút
        if 25 <= minutes <= 35:
            key = f"warn30_{key_base}"
            if not already_sent(state, key):
                msg = "🚨 30 PHÚT NỮA CÓ TIN MẠNH\n\n"
                msg += f"Tin: {e['title']}\n"
                msg += f"Giờ: {e['jst'].strftime('%m-%d %H:%M JST')}\n"
                msg += f"Forecast: {e['forecast']}\n"
                msg += f"Previous: {e['previous']}\n\n"
                msg += "⚠️ XAUUSD có thể giật mạnh. Không FOMO trước tin."
                send_telegram(msg)
                mark_sent(state, key)
                sent_any = True

        # Cảnh báo 15 phút
        if 10 <= minutes <= 20:
            key = f"warn15_{key_base}"
            if not already_sent(state, key):
                msg = "⚠️ 15 PHÚT NỮA CÓ TIN MẠNH\n\n"
                msg += f"Tin: {e['title']}\n"
                msg += f"Giờ: {e['jst'].strftime('%m-%d %H:%M JST')}\n"
                msg += f"Forecast: {e['forecast']}\n"
                msg += f"Previous: {e['previous']}\n\n"
                msg += "Quan sát spread và nến phản ứng. Không all-in."
                send_telegram(msg)
                mark_sent(state, key)
                sent_any = True

        # Cảnh báo 5 phút
        if 2 <= minutes <= 8:
            key = f"warn5_{key_base}"
            if not already_sent(state, key):
                msg = "🔥 5 PHÚT NỮA CÓ TIN MẠNH\n\n"
                msg += f"Tin: {e['title']}\n"
                msg += f"Giờ: {e['jst'].strftime('%m-%d %H:%M JST')}\n\n"
                msg += "⚠️ Hạn chế vào lệnh mới. Chờ Actual và phản ứng giá."
                send_telegram(msg)
                mark_sent(state, key)
                sent_any = True

        # Actual ra sau tin
        if e["actual"] != "-" and -30 <= minutes <= 30:
            key = f"actual_{key_base}_{e['actual']}"
            if not already_sent(state, key):
                bias, score = gold_bias(e["title"], e["actual"], e["forecast"])

                msg = "🔥 USD NEWS RELEASE\n\n"
                msg += f"Tin: {e['title']}\n"
                msg += f"Giờ: {e['jst'].strftime('%m-%d %H:%M JST')}\n"
                msg += f"Actual: {e['actual']}\n"
                msg += f"Forecast: {e['forecast']}\n"
                msg += f"Previous: {e['previous']}\n\n"
                msg += f"{bias}\n"
                msg += f"Gold Score: {score}\n\n"
                msg += "⚠️ Chờ nến xác nhận. Không vào lệnh chỉ vì tin vừa ra."
                send_telegram(msg)
                mark_sent(state, key)
                sent_any = True

    if not sent_any:
        print("No alert to send now.")

def manual_test(events, state):
    msg = "✅ BOT TEST OK\n\n"
    msg += f"MODE: test\n"
    
