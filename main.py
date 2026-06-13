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
]

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def already_sent(state, key):
    return state.get(key) is True

def mark_sent(state, key):
    state[key] = True

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=20)
    print(r.status_code, r.text)

def is_important(title):
    return any(k.lower() in title.lower() for k in IMPORTANT)

def to_number(v):
    if not v or v == "-":
        return None
    try:
        return float(
            v.replace("%", "")
             .replace("K", "")
             .replace("M", "")
             .replace("B", "")
             .replace(",", "")
             .strip()
        )
    except:
        return None

def parse_event_time(date_str, time_str):
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%m-%d-%Y %I:%M%p")
        return dt.replace(tzinfo=NY).astimezone(JST)
    except:
        return None

def gold_bias(title, actual, forecast):
    a = to_number(actual)
    f = to_number(forecast)

    if a is None or f is None:
        return "⏳ Chưa có Actual", 0

    t = title.lower()

    inflation = ["cpi", "ppi", "retail sales", "interest rate", "federal funds"]
    jobs = ["non-farm", "nonfarm", "nfp"]

    if any(x in t for x in inflation):
        if a > f:
            return "🔴 SELL GOLD - USD mạnh hơn dự báo", -3
        if a < f:
            return "🟢 BUY GOLD - USD yếu hơn dự báo", 3

    if any(x in t for x in jobs):
        if a > f:
            return "🔴 SELL GOLD - việc làm mạnh", -3
        if a < f:
            return "🟢 BUY GOLD - việc làm yếu", 3

    if "unemployment" in t:
        if a > f:
            return "🟢 BUY GOLD - thất nghiệp cao", 2
        if a < f:
            return "🔴 SELL GOLD - thất nghiệp thấp", -2

    return "⚪ WAIT / NO TRADE", 0

def event_key(e):
    return f"{e['title']}_{e['date']}_{e['time']}"

def get_events():
    xml = requests.get(URL, timeout=20).text
    soup = BeautifulSoup(xml, "xml")
    events = []

    for e in soup.find_all("event"):
        country = e.find("country")
        impact = e.find("impact")
        title = e.find("title")
        date = e.find("date")
        time = e.find("time")
        forecast = e.find("forecast")
        previous = e.find("previous")
        actual = e.find("actual")

        country = country.text.strip() if country else ""
        impact = impact.text.strip() if impact else ""
        title = title.text.strip() if title else ""
        date = date.text.strip() if date else ""
        time = time.text.strip() if time else ""
        forecast = forecast.text.strip() if forecast else "-"
        previous = previous.text.strip() if previous else "-"
        actual = actual.text.strip() if actual else "-"

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

    return events

def today_events(events):
    result = []

    now = datetime.now(JST)

    for e in events:
        if not e["jst"]:
            continue

        diff = (e["jst"] - now).total_seconds()

        if -86400 <= diff <= 86400 * 3:
            result.append(e)

    return result

def daily_report(events, state):
    today = today_events(events)
    today_key = f"daily_{datetime.now(JST).strftime('%Y-%m-%d')}"

    if already_sent(state, today_key):
        print("Daily report already sent.")
        return

    msg = "🔥 HIGH IMPACT USD - TIN HÔM NAY ẢNH HƯỞNG VÀNG\n\n"

    if not today:
        msg += "⚪ Hôm nay không có tin USD High Impact quan trọng.\n"
        msg += "Không nên ép lệnh theo tin."
        send_telegram(msg)
        mark_sent(state, today_key)
        return

    total = 0

    for e in today:
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

    for e in events:
        if not e["jst"]:
            continue

        minutes = (e["jst"] - now).total_seconds() / 60
        key_base = event_key(e)

        if 28 <= minutes <= 32:
            key = f"warn30_{key_base}"
            if not already_sent(state, key):
                msg = "🚨 30 PHÚT NỮA CÓ TIN MẠNH\n\n"
                msg += f"Tin: {e['title']}\n"
                msg += f"Giờ: {e['jst'].strftime('%m-%d %H:%M JST')}\n"
                msg += f"Forecast: {e['forecast']}\n"
                msg += f"Previous: {e['previous']}\n\n"
                msg += "⚠️ XAUUSD có thể biến động mạnh. Không FOMO trước tin."
                send_telegram(msg)
                mark_sent(state, key)

        if 13 <= minutes <= 17:
            key = f"warn15_{key_base}"
            if not already_sent(state, key):
                msg = "⚠️ 15 PHÚT NỮA CÓ TIN MẠNH\n\n"
                msg += f"Tin: {e['title']}\n"
                msg += f"Giờ: {e['jst'].strftime('%m-%d %H:%M JST')}\n"
                msg += f"Forecast: {e['forecast']}\n"
                msg += f"Previous: {e['previous']}\n"
                send_telegram(msg)
                mark_sent(state, key)

        if 3 <= minutes <= 7:
            key = f"warn5_{key_base}"
            if not already_sent(state, key):
                msg = "🔥 5 PHÚT NỮA CÓ TIN MẠNH\n\n"
                msg += f"Tin: {e['title']}\n"
                msg += "⚠️ Hạn chế vào lệnh mới. Chờ Actual."
                send_telegram(msg)
                mark_sent(state, key)

        if e["actual"] != "-" and -10 <= minutes <= 15:
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
                msg += f"Gold Score: {score}"
                send_telegram(msg)
                mark_sent(state, key)

try:
    state = load_state()
    events = get_events()

    if MODE == "daily":
        daily_report(events, state)
    elif MODE == "check":
        check_events(events, state)
    else:
        send_telegram(f"⚠️ MODE lỗi: {MODE}")

    save_state(state)

except Exception as e:
    send_telegram(f"❌ ERROR\n{e}")
