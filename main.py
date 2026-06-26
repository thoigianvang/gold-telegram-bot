import hashlib
import os
import json
import requests
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
MODE = os.getenv("MODE", "daily")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
BOT_VERSION = "V3.0 STABLE"
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
STATE_FILE = "sent.json"

NY = ZoneInfo("America/New_York")
JST = ZoneInfo("Asia/Tokyo")

IMPORTANT_EVENTS = [
    "CPI", "Core CPI",
    "PPI", "Core PPI",
    "Non-Farm", "Nonfarm", "NFP",
    "FOMC", "Federal Funds", "Interest Rate",
    "Powell",
    "Unemployment",
    "Retail Sales",
    "GDP", "ISM", "PMI", "JOLTS", "ADP",
]

NEWS_QUERIES = [
    "gold price dollar yields Fed",
    "XAUUSD gold market Federal Reserve",
    "gold price geopolitical risk",
    "US dollar Treasury yields gold",
]

BUY_NEWS_WORDS = [
    "safe haven", "geopolitical", "war", "conflict", "tension",
    "dollar falls", "dollar weak", "yields fall", "yields drop",
    "fed cut", "rate cut", "dovish", "inflation cools",
    "recession", "bank crisis",
]

SELL_NEWS_WORDS = [
    "dollar rises", "dollar strong", "dollar strengthens",
    "yields rise", "yields climb", "hawkish",
    "rate hike", "higher for longer", "inflation hot",
    "strong jobs", "retail sales strong",
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

    chunks = []
    while len(text) > 3900:
        cut = text.rfind("\n", 0, 3900)
        if cut == -1:
            cut = 3900
        chunks.append(text[:cut])
        text = text[cut:].strip()
    chunks.append(text)

    for chunk in chunks:
        r = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": chunk,
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        print("TELEGRAM:", r.status_code, r.text)

        if r.status_code != 200:
            raise RuntimeError(f"Telegram send failed: {r.status_code} {r.text}")


def clean_value(v):
    if not v:
        return "-"
    v = v.strip()
    return v if v else "-"


def is_important_event(title):
    title_l = title.lower()
    return any(k.lower() in title_l for k in IMPORTANT_EVENTS)


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
    if not date_str or not time_str:
        return None

    if time_str.lower() in ["all day", "tentative"]:
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
    safe_title = (
        e["title"]
        .replace(" ", "_")
        .replace("/", "_")
        .replace(":", "_")
        .replace(",", "")
    )
    return f"{e['date']}_{e['time']}_{safe_title}"


def gold_bias_from_event(title, actual, forecast):
    title_l = str(title).lower()
    actual_s = str(actual).strip()
    forecast_s = str(forecast).strip()

    if actual_s in ["", "-", "None", "null"]:
        return "⏳ Chưa có Actual", 0

    try:
        a = float(actual_s.replace("%", "").replace(",", ""))
        f = float(forecast_s.replace("%", "").replace(",", ""))

        if "federal funds" in title_l or "interest rate" in title_l:
            if a > f:
                return "🔴 Hawkish Fed / SELL GOLD", -5
            elif a < f:
                return "🟢 Dovish Fed / BUY GOLD", 5
            else:
                return "⚪ Đúng forecast / WAIT", 0

        if a > f:
            return "🔴 USD mạnh / SELL GOLD", -2
        elif a < f:
            return "🟢 USD yếu / BUY GOLD", 2
        else:
            return "⚪ Đúng forecast / WAIT", 0

    except:
        return "⚪ Không đọc được Actual", 0


def score_news_title(title):
    t = title.lower()
    score = 0
    reasons = []

    bullish = [
        "gold rises", "gold gains", "gold climbs", "gold rebounds",
        "gold extends gains", "gold hits record", "gold nears record",
        "safe haven", "geopolitical risk", "war", "conflict",
        "fed rate cut", "rate cut bets", "dovish fed",
        "dollar falls", "dollar weakens", "weaker dollar",
        "yields fall", "yields drop", "treasury yields fall",
        "inflation cools", "recession fears"
    ]

    bearish = [
        "gold falls", "gold drops", "gold slips", "gold tumbles",
        "gold retreats", "gold under pressure", "gold prices fall",
        "gold prices tumble", "stronger dollar", "dollar rises",
        "dollar strengthens", "dollar hits", "yields rise",
        "yields climb", "treasury yields rise", "hawkish fed",
        "rate hike", "higher for longer", "inflation concerns",
        "strong jobs", "strong retail sales"
    ]

    for word in bullish:
        if word in t:
            score += 2
            reasons.append("Bullish Gold")

    for word in bearish:
        if word in t:
            score -= 2
            reasons.append("Bearish Gold")

    # Gold lên nhưng lý do là USD/yield yếu = bullish rõ
    if "gold" in t and ("weaker dollar" in t or "dollar falls" in t or "yields fall" in t):
        score += 2
        reasons.append("Gold supported by weak USD/yields")

    # Gold giảm vì USD/yield mạnh = bearish rõ
    if "gold" in t and ("stronger dollar" in t or "dollar rises" in t or "yields rise" in t):
        score -= 2
        reasons.append("Gold pressured by strong USD/yields")

    # Nếu có cả bullish và bearish thì giảm độ mạnh
    if any("Bullish" in r for r in reasons) and any("Bearish" in r for r in reasons):
        score = int(score / 2)
        reasons.append("Mixed signal")

    score = clamp_score(score, -4, 4)

    return score, reasons
def parse_number(value):
    try:
        if value is None:
            return None

        value = str(value)
        value = value.replace("%", "")
        value = value.replace(",", "")
        value = value.strip()

        if value in ["", "-", "None"]:
            return None

        return float(value)

    except:
        return None
def get_events():
    r = requests.get(CALENDAR_URL, timeout=20)
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

        if country == "USD" and impact == "High" and is_important_event(title):
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

def get_today_all_events():
    r = requests.get(CALENDAR_URL, timeout=20)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "xml")
    today = datetime.now(JST).date()
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

        if not jst_time:
            continue

        if jst_time.date() != today:
            continue

        events.append({
            "country": country,
            "impact": impact,
            "title": title,
            "date": date,
            "time": time,
            "forecast": forecast,
            "previous": previous,
            "actual": actual,
            "jst": jst_time,
        })

    events.sort(key=lambda x: x["jst"])
    return events
def daily_all_events_report(state, force=False):
    now = datetime.now(JST)
    today = now.strftime("%Y-%m-%d")
    key = f"daily_all_events_{today}"

    if not force and already_sent(state, key):
        print("Daily all events report already sent.")
        return

    events = get_today_all_events()

    msg = "📅 LỊCH KINH TẾ HÔM NAY\n\n"
    msg += f"🕒 Update: {now.strftime('%m-%d %H:%M JST')}\n\n"

    if not events:
        msg += "Không có dữ liệu lịch kinh tế hôm nay."
        send_telegram(msg)
        mark_sent(state, key)
        return

    for e in events[:30]:
        impact_icon = "🔴" if e["impact"] == "High" else "🟠" if e["impact"] == "Medium" else "🟡"

        msg += f"{impact_icon} {e['jst'].strftime('%H:%M')} | {e['country']} | {e['impact']}\n"
        msg += f"{e['title']}\n"
        msg += f"Actual: {e['actual']} | Forecast: {e['forecast']} | Previous: {e['previous']}\n\n"

    msg += "⚠️ Đây là lịch kinh tế tổng hợp, không phải tín hiệu vào lệnh."

    send_telegram(msg)
    mark_sent(state, key)
def target_events(events):
    now = datetime.now(JST)
    result = []

    for e in events:
        if not e["jst"]:
            continue

        diff = (e["jst"] - now).total_seconds()

        if -6 * 3600 <= diff <= 3 * 86400:
            result.append(e)

    return result


def get_gold_news(limit=8):
    items = []
    seen_keys = set()

    for query in NEWS_QUERIES:
        rss_url = (
            "https://news.google.com/rss/search?q="
            + quote_plus(query)
            + "&hl=en-US&gl=US&ceid=US:en"
        )

        try:
            r = requests.get(rss_url, timeout=20)
            r.raise_for_status()

            soup = BeautifulSoup(r.text, "xml")

            for item in soup.find_all("item"):
                title = clean_value(item.find("title").text if item.find("title") else "")
                pub_date = clean_value(item.find("pubDate").text if item.find("pubDate") else "")
                link = clean_value(item.find("link").text if item.find("link") else "")

                if title == "-":
                    continue

                # Tạo key để lọc tin trùng / gần trùng
                key = title.lower()

                remove_words = [
                    "gold", "xauusd", "xau/usd",
                    "fed", "federal reserve",
                    "dollar", "usd",
                    "treasury", "yields", "yield",
                    "price", "prices",
                    "market", "markets",
                    "today", "forecast",
                    "analysis", "outlook",
                ]

                for w in remove_words:
                    key = key.replace(w, "")

                # Bỏ tên nguồn phía sau dấu "-"
                if " - " in key:
                    key = key.rsplit(" - ", 1)[0]

                key = " ".join(key.split())
                key = key[:90]

                if key in seen_keys:
                    continue

                seen_keys.add(key)

                score, reasons = score_news_title(title)

                items.append({
                    "title": title,
                    "vi_title": translate_news_title_vi(title),
                    "pubDate": pub_date,
                    "link": link,
                    "score": score,
                    "reasons": reasons,
                })

                if len(items) >= limit:
                    return items

        except Exception as e:
            print("GOLD NEWS ERROR:", str(e))
            continue

    return items
def daily_report(events, state, force=False):
    today = datetime.now(JST).strftime("%Y-%m-%d")
    daily_key = f"daily_{today}"

    if not force and already_sent(state, daily_key):
        print("Daily report already sent.")
        return

    selected = target_events(events)

    msg = "📅 LỊCH USD HIGH IMPACT SẮP TỚI\n\n"

    if not selected:
        no_news_key = f"no_news_{today}"

        if not force and already_sent(state, no_news_key):
            print("No-news already sent.")
            return

        msg += "⚪ Hiện chưa có tin USD High Impact quan trọng.\n"
        msg += "Không nên ép lệnh theo tin.\n\n"
        msg += f"🕒 Update: {datetime.now(JST).strftime('%m-%d %H:%M JST')}"

        send_telegram(msg)
        mark_sent(state, no_news_key)
        mark_sent(state, daily_key)
        return

    total = 0

    for e in selected:
        bias, score = gold_bias_from_event(e["title"], e["actual"], e["forecast"])
        if e["actual"] == "-":
            bias = "⏳ Chưa có Actual - chỉ là lịch sắp tới"
            score = 0
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
        msg += "⚪ Kết luận: Chưa có Actual - chỉ theo dõi lịch, không vào lệnh theo tin."

    send_telegram(msg)
    mark_sent(state, daily_key)


def translate_news_title_vi(title):
    source = ""

    if " - " in title:
        parts = title.rsplit(" - ", 1)
        title_main = parts[0].strip()
        source = parts[1].strip()
    else:
        title_main = title.strip()

    vi = title_main

    replacements = {
        "Gold": "Vàng",
        "gold": "vàng",
        "silver": "bạc",
        "bitcoin": "Bitcoin",
        "traders": "nhà giao dịch",
        "Fed": "Fed",
        "rate hike": "tăng lãi suất",
        "rate cut": "cắt giảm lãi suất",
        "dollar": "đồng USD",
        "yields": "lợi suất trái phiếu",
        "Treasury yields": "lợi suất trái phiếu Mỹ",
        "falls": "giảm",
        "fall": "giảm",
        "slips": "trượt giảm",
        "hits": "chạm",
        "low": "mức thấp",
        "high": "mức cao",
        "forecast": "dự báo",
        "pressure": "áp lực",
        "surge": "tăng mạnh",
        "hawkish": "diều hâu",
        "dovish": "bồ câu",
        "FOMC": "FOMC",
    }

    for en, vn in replacements.items():
        vi = vi.replace(en, vn)

    if source:
        return f"{vi} - Nguồn: {source}"

    return vi


def gold_news_update(state, force=False):
    now = datetime.now(JST)
    key = f"gold_news_{now.strftime('%Y-%m-%d_%H')}"

    if False:
        return

    news = get_gold_news(limit=8)

    msg = "📰 GOLD NEWS UPDATE - TIN ẢNH HƯỞNG VÀNG\n\n"
    msg += f"🕒 Update: {now.strftime('%m-%d %H:%M JST')}\n\n"

    if not news:
        msg += "⚪ Chưa có headline vàng mới so với lần quét trước.\n"
        msg += "✅ Gold News Scanner vẫn đang hoạt động.\n"
        msg += "Ưu tiên theo dõi USD High Impact, DXY, US10Y và phản ứng giá.\n"
    news_hash = hashlib.md5(msg.encode()).hexdigest()

    if state.get("last_news_hash") == news_hash:
        print("News unchanged, skip sending")
        return

    state["last_news_hash"] = news_hash

    send_telegram(msg)
    mark_sent(state, key)
    return

    total = 0

    for i, item in enumerate(news, 1):
        total += item["score"]

        if item["score"] > 0:
            bias_icon = "🟢"
        elif item["score"] < 0:
            bias_icon = "🔴"
        else:
            bias_icon = "⚪"

        msg += f"{i}. {bias_icon} {item['vi_title']}\n"

    market_v6 = market_bias_engine(total)

    msg += "\n----------------------\n"
    msg += "📊 MARKET BIAS V6\n"
    msg += f"News Score: {total}\n"
    msg += f"DXY Change: {market_v6['dxy_change']}%\n"
    msg += f"US10Y Change: {market_v6['us10y_change']}%\n"
    msg += f"Dollar Score: {market_v6['dollar_score']}\n"
    msg += f"Yield Score: {market_v6['yield_score']}\n"
    msg += f"Total Gold Score: {market_v6['total']}\n"

    if market_v6["total"] >= 4:
        bias = "🟢 STRONG BUY GOLD"

    elif market_v6["total"] >= 2:
        bias = "🟢 BUY GOLD"

    elif market_v6["total"] <= -4:
        bias = "🔴 STRONG SELL GOLD"

    elif market_v6["total"] <= -2:
        bias = "🔴 SELL GOLD"

    else:
        bias = "⚪ WAIT"

    msg += "\n\n⚠️ Đây là bias theo tin tức + DXY + US10Y, không phải lệnh vào trực tiếp."

    send_telegram(msg)
    mark_sent(state, key)
def score_dollar_news(news):
    score = 0

    for item in news:
        t = item["title"].lower()

        if "dollar" in t:
            if (
                "strong" in t
                or "gains" in t
                or "rises" in t
                or "higher" in t
                or "lift" in t
            ):
                score -= 2
            elif (
                "weak" in t
                or "falls" in t
                or "lower" in t
                or "drops" in t
            ):
                score += 2

    return score
def score_yield_news(news):
    score = 0

    for item in news:
        t = item["title"].lower()

        if "yield" in t or "yields" in t:
            if (
                "rise" in t
                or "rises" in t
                or "higher" in t
                or "surge" in t
                or "lift" in t
            ):
                score -= 2
            elif (
                "fall" in t
                or "falls" in t
                or "lower" in t
                or "drop" in t
            ):
                score += 2

    return score
def clamp_score(score, min_value=-4, max_value=4):
    return max(min(score, max_value), min_value)


def calculate_probability(total_score):

    if total_score >= 6:
        buy_prob = 85

    elif total_score >= 4:
        buy_prob = 75

    elif total_score >= 2:
        buy_prob = 65

    elif total_score >= 1:
        buy_prob = 55

    elif total_score == 0:
        buy_prob = 50

    elif total_score <= -6:
        buy_prob = 15

    elif total_score <= -4:
        buy_prob = 25

    elif total_score <= -2:
        buy_prob = 35

    else:
        buy_prob = 45

    sell_prob = 100 - buy_prob

    return buy_prob, sell_prob
def build_trade_plan(gold_trend, total_score):
    price = float(gold_trend.get("price", 0))
    high = float(gold_trend.get("high", 0))
    low = float(gold_trend.get("low", 0))
    change_pct = float(gold_trend.get("change_pct", 0))

    if price <= 0:
        return {
            "direction": "WAIT",
            "entry": "-",
            "sl": "-",
            "tp1": "-",
            "tp2": "-",
            "tp3": "-",
            "rr": "-",
            "note": "Không có giá XAU/USD hợp lệ."
        }

    day_range = high - low

    if day_range <= 0:
        day_range = price * 0.003

    atr_like = max(day_range, price * 0.002)

    if total_score >= 5:
        direction = "BUY"
        entry_low = price - atr_like * 0.35
        entry_high = price - atr_like * 0.15
        sl = entry_low - atr_like * 0.7
        tp1 = price + atr_like * 0.6
        tp2 = price + atr_like * 1.1
        tp3 = price + atr_like * 1.8
        note = "BUY bias mạnh. Chỉ BUY khi giá hồi về vùng entry và có nến xác nhận."

    elif total_score >= 2:
        direction = "BUY"
        entry_low = price - atr_like * 0.25
        entry_high = price - atr_like * 0.10
        sl = entry_low - atr_like * 0.6
        tp1 = price + atr_like * 0.45
        tp2 = price + atr_like * 0.9
        tp3 = price + atr_like * 1.4
        note = "BUY bias nhẹ. Không BUY đuổi."

    elif total_score <= -5:
        direction = "SELL"
        entry_low = price + atr_like * 0.15
        entry_high = price + atr_like * 0.35
        sl = entry_high + atr_like * 0.7
        tp1 = price - atr_like * 0.6
        tp2 = price - atr_like * 1.1
        tp3 = price - atr_like * 1.8
        note = "SELL bias mạnh. Chỉ SELL khi giá hồi lên vùng entry và có nến xác nhận."

    elif total_score <= -2:
        direction = "SELL"
        entry_low = price + atr_like * 0.10
        entry_high = price + atr_like * 0.25
        sl = entry_high + atr_like * 0.6
        tp1 = price - atr_like * 0.45
        tp2 = price - atr_like * 0.9
        tp3 = price - atr_like * 1.4
        note = "SELL bias nhẹ. Không SELL đuổi."

    else:
        return {
            "direction": "WAIT",
            "entry": "-",
            "sl": "-",
            "tp1": "-",
            "tp2": "-",
            "tp3": "-",
            "rr": "-",
            "note": "Điểm chưa đủ mạnh. Không vào lệnh."
        }

    risk = abs(((entry_low + entry_high) / 2) - sl)
    reward = abs(tp3 - ((entry_low + entry_high) / 2))

    if risk > 0:
        rr = round(reward / risk, 2)
    else:
        rr = "-"

    return {
        "direction": direction,
        "entry": f"{round(entry_low, 2)} - {round(entry_high, 2)}",
        "sl": round(sl, 2),
        "tp1": round(tp1, 2),
        "tp2": round(tp2, 2),
        "tp3": round(tp3, 2),
        "rr": rr,
        "note": note
    }
def format_trade_plan(gold_trend, plan):
    price = gold_trend.get("price", "-")
    open_price = gold_trend.get("open", "-")
    high = gold_trend.get("high", "-")
    low = gold_trend.get("low", "-")
    change_pct = gold_trend.get("change_pct", "-")
    trend = gold_trend.get("trend", "-")
    source = gold_trend.get("source", "-")

    direction = plan.get("direction", "WAIT")

    if direction == "BUY":
        icon = "🟢"
    elif direction == "SELL":
        icon = "🔴"
    else:
        icon = "⚪"

    msg = "📊 XAU/USD TRADE PLAN V4\n\n"

    msg += "🥇 GOLD US$/OZ\n"
    msg += f"Price: {price}\n"
    msg += f"Open: {open_price}\n"
    msg += f"High: {high}\n"
    msg += f"Low: {low}\n"
    msg += f"Change: {change_pct}%\n"
    msg += f"Trend: {trend}\n"
    msg += f"Source: {source}\n\n"

    msg += "🎯 PLAN\n"
    msg += f"{icon} Direction: {direction}\n"
    msg += f"Entry Zone: {plan.get('entry')}\n"
    msg += f"Stop Loss: {plan.get('sl')}\n"
    msg += f"TP1: {plan.get('tp1')}\n"
    msg += f"TP2: {plan.get('tp2')}\n"
    msg += f"TP3: {plan.get('tp3')}\n"
    msg += f"RR: {plan.get('rr')}\n\n"

    msg += "📝 NOTE\n"
    msg += f"{plan.get('note')}\n\n"

    msg += "⚠️ Đây là kế hoạch theo mô hình bias, không phải lệnh vào trực tiếp."
    msg += "\nChỉ vào lệnh khi có nến xác nhận và spread ổn."

    return msg
def get_market_signal():
    result = {
        "dxy_change": None,
        "us10y_change": None,
        "dollar_score": 0,
        "yield_score": 0,
    }

    try:
        dxy = yf.Ticker("DX-Y.NYB").history(period="2d")
        if len(dxy) >= 2:
            prev = dxy["Close"].iloc[-2]
            last = dxy["Close"].iloc[-1]
            change = ((last - prev) / prev) * 100

            result["dxy_change"] = round(change, 2)

            if change >= 0.3:
                result["dollar_score"] = -3
            elif change <= -0.3:
                result["dollar_score"] = 3

        us10y = yf.Ticker("^TNX").history(period="2d")
        if len(us10y) >= 2:
            prev = us10y["Close"].iloc[-2]
            last = us10y["Close"].iloc[-1]
            change = last - prev

            result["us10y_change"] = round(change, 2)

            if change >= 0.05:
                result["yield_score"] = -3
            elif change <= -0.05:
                result["yield_score"] = 3

    except Exception as e:
        print("MARKET ERROR:", e)

    return result

import yfinance as yf

def get_dxy_change():
    try:
        dxy = yf.Ticker("DX-Y.NYB")

        hist = dxy.history(period="2d")

        if len(hist) < 2:
            return 0

        prev = hist["Close"].iloc[-2]
        curr = hist["Close"].iloc[-1]

        return round((curr - prev) / prev * 100, 2)

    except Exception as e:
        print("DXY ERROR:", e)
        return 0


def get_us10y_change():
    try:
        us10y = yf.Ticker("^TNX")
        hist = us10y.history(period="10d")

        if hist is None or hist.empty or len(hist) < 2:
            return 0

        closes = hist["Close"].dropna()

        if len(closes) < 2:
            return 0

        prev = float(closes.iloc[-2])
        curr = float(closes.iloc[-1])

        change = ((curr - prev) / prev) * 100

        print("US10Y PREV:", prev)
        print("US10Y CURR:", curr)
        print("US10Y CHANGE:", change)

        return round(change, 2)

    except Exception as e:
        print("US10Y ERROR:", e)
        return 0
def market_bias_engine(news_score=0):
    dxy_change = get_dxy_change()
    us10y_change = get_us10y_change()

    print("DXY:", dxy_change)
    print("US10Y:", us10y_change)

    dollar_score = 0
    yield_score = 0

    # DXY tăng = USD mạnh = thường xấu cho vàng
    if dxy_change >= 0.30:
        dollar_score = -5
    elif dxy_change >= 0.15:
        dollar_score = -4
    elif dxy_change >= 0.05:
        dollar_score = -2
    elif dxy_change <= -0.30:
        dollar_score = 5
    elif dxy_change <= -0.15:
        dollar_score = 4
    elif dxy_change <= -0.05:
        dollar_score = 2

    # US10Y tăng = lợi suất tăng = thường xấu cho vàng
    if us10y_change >= 0.30:
        yield_score = -5
    elif us10y_change >= 0.15:
        yield_score = -4
    elif us10y_change >= 0.05:
        yield_score = -2
    elif us10y_change <= -0.30:
        yield_score = 5
    elif us10y_change <= -0.15:
        yield_score = 4
    elif us10y_change <= -0.05:
        yield_score = 2

    total_score = news_score + dollar_score + yield_score

    return {
        "dxy_change": dxy_change,
        "us10y_change": us10y_change,
        "dollar_score": dollar_score,
        "yield_score": yield_score,
        "total": total_score
    }
def format_actual_alert(event, market_v6):

    title = event.get("title", "")
    actual = event.get("actual", "-")
    forecast = event.get("forecast", "-")
    previous = event.get("previous", "-")

    actual_num = parse_number(actual)
    forecast_num = parse_number(forecast)

    deviation_text = "N/A"
    event_bias = "WAIT"
    event_score = 0

    if actual_num is not None and forecast_num is not None:
        deviation = actual_num - forecast_num
        deviation_text = f"{deviation:+.2f}"
    impact_strength = "NORMAL"

    if forecast_num != 0:

        ratio = abs(deviation) / abs(forecast_num)

        if ratio >= 0.30:
            impact_strength = "🔥 RẤT MẠNH"

        elif ratio >= 0.15:
            impact_strength = "⚡ MẠNH"

        else:
            impact_strength = "🟡 TRUNG BÌNH"
            title_l = title.lower()

        bad_when_higher = [
            "cpi", "ppi", "inflation", "core",
            "payroll", "nonfarm", "nfp",
            "unemployment claims", "jobless claims",
            "retail sales", "gdp",
            "ism", "pmi"
        ]

        good_when_higher = [
            "unemployment rate"
        ]

        if any(k in title_l for k in bad_when_higher):
            if deviation > 0:
                event_bias = "SELL GOLD BIAS"
                event_score = -4
            elif deviation < 0:
                event_bias = "BUY GOLD BIAS"
                event_score = 4

        elif any(k in title_l for k in good_when_higher):
            if deviation > 0:
                event_bias = "BUY GOLD BIAS"
                event_score = 4
            elif deviation < 0:
                event_bias = "SELL GOLD BIAS"
                event_score = -4

        else:
            if deviation > 0:
                event_bias = "SELL GOLD BIAS"
                event_score = -2
            elif deviation < 0:
                event_bias = "BUY GOLD BIAS"
                event_score = 2

    market_score = market_v6.get("total", 0)
    dxy_change = market_v6.get("dxy_change", 0)
    us10y_change = market_v6.get("us10y_change", 0)

    final_score = event_score + market_score

    if final_score >= 5:
        final_bias = "🟢 STRONG BUY GOLD"
        action = "BUY WATCH - chờ giá hồi về hỗ trợ rồi xác nhận BUY"
    elif final_score >= 2:
        final_bias = "🟢 BUY GOLD nhẹ"
        action = "BUY WATCH - chỉ buy khi có nến xác nhận"
    elif final_score <= -5:
        final_bias = "🔴 STRONG SELL GOLD"
        action = "SELL WATCH - chờ giá hồi lên kháng cự rồi xác nhận SELL"
    elif final_score <= -2:
        final_bias = "🔴 SELL GOLD nhẹ"
        action = "SELL WATCH - chỉ sell khi có nến xác nhận"
    else:
        final_bias = "⚪ WAIT"
        action = "WAIT - tin chưa đủ rõ hoặc market đang lệch nhau"

    confidence = min(95, 50 + abs(final_score) * 5)

    msg = "🚨 TIN USD VỪA RA\n\n"
    msg += f"Event: {title}\n"
    msg += f"Actual: {actual}\n"
    msg += f"Forecast: {forecast}\n"
    msg += f"Previous: {previous}\n"
    msg += f"Deviation: {deviation_text}\n"
    msg += f"Độ mạnh tin: {impact_strength}\n\n"

    msg += "📌 Event Impact\n"
    msg += f"Event Bias: {event_bias}\n"
    msg += f"Event Score: {event_score}\n\n"

    msg += "📊 Market Confirmation\n"
    msg += f"DXY: {dxy_change}%\n"
    msg += f"US10Y: {us10y_change}%\n"
    msg += f"Market Score: {market_score}\n\n"

    msg += "🎯 Final Decision\n"
    msg += f"Final Score: {final_score}\n"
    msg += f"Confidence: {confidence}%\n"
    msg += f"Bias: {final_bias}\n"
    msg += f"Action: {action}\n\n"

    msg += "⚠️ Không vào lệnh ngay khi tin vừa ra. Chờ spread ổn, nến xác nhận."

    return msg
def score_fomc_from_news(news):
    score = 0

    for item in news:
        title = item.get("title", "").lower()

        if "hawkish fed" in title or "rate hike" in title or "higher for longer" in title:
            score -= 4

        if "dovish fed" in title or "rate cut" in title or "weaker dollar" in title:
            score += 4

        if "fed" in title and "yield" in title and "rise" in title:
            score -= 3

        if "fed" in title and "yield" in title and "fall" in title:
            score += 3

    return score
def session_alert(state, total_score):

    now = datetime.now(JST)
    session_key = f"session_alert_{now.strftime('%Y-%m-%d')}_{now.hour}"

    if already_sent(state, session_key):
        print("Session alert already sent.")
        return

    if total_score >= 3:
        action = (
            "🟢 BUY WATCH\n\n"
            "BUY STOP trên đỉnh nến tin\n"
            "SL dưới đáy nến tin\n\n"
            "Không BUY market ngay."
        )

    elif total_score <= -3:
        action = (
            "🔴 SELL WATCH\n\n"
            "SELL STOP dưới đáy nến tin\n"
            "SL trên đỉnh nến tin\n\n"
            "Không SELL market ngay."
        )

    else:
        action = (
            "⚪ WAIT\n\n"
            "Chờ phản ứng giá rõ hơn."
        )

    msg = "🌍 SESSION OPEN ALERT\n\n"
    msg += f"Time: {now.strftime('%m-%d %H:%M JST')}\n"
    msg += f"{icon} Bias: {bias}\n"
    msg += f"Gold Score: {total_score}\n\n"
    msg += "⚠️ Đây là cảnh báo phiên, không phải lệnh vào trực tiếp."

    send_telegram(msg)
    mark_sent(state, session_key)
def get_gold_spot_price():
    try:
        if not TWELVE_DATA_API_KEY:
            print("TWELVE DATA API KEY MISSING")
            return None

        url = "https://api.twelvedata.com/price"

        params = {
            "symbol": "XAU/USD",
            "apikey": TWELVE_DATA_API_KEY
        }

        r = requests.get(url, params=params, timeout=20)
        print("TWELVE DATA STATUS:", r.status_code)
        print("TWELVE DATA RESPONSE:", r.text[:300])

        r.raise_for_status()
        data = r.json()

        price = data.get("price")

        if not price:
            print("TWELVE DATA PRICE EMPTY:", data)
            return None

        return round(float(price), 2)

    except Exception as e:
        print("TWELVE DATA PRICE ERROR:", str(e))
        return None
def get_gold_ohlc():
    try:
        if not TWELVE_DATA_API_KEY:
            print("TWELVE DATA API KEY MISSING")
            return None

        url = "https://api.twelvedata.com/quote"

        params = {
            "symbol": "XAU/USD",
            "apikey": TWELVE_DATA_API_KEY
        }

        r = requests.get(url, params=params, timeout=20)
        print("TWELVE DATA QUOTE STATUS:", r.status_code)
        print("TWELVE DATA QUOTE RESPONSE:", r.text[:300])

        r.raise_for_status()
        data = r.json()

        if "close" not in data:
            print("TWELVE DATA QUOTE EMPTY:", data)
            return None

        price = float(data.get("close", 0))
        open_price = float(data.get("open", 0))
        high = float(data.get("high", 0))
        low = float(data.get("low", 0))

        if open_price > 0:
            change_pct = round(((price - open_price) / open_price) * 100, 2)
        else:
            change_pct = 0

        return {
            "symbol": "XAU/USD",
            "price": round(price, 2),
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "change_pct": change_pct,
            "source": "TwelveData"
        }

    except Exception as e:
        print("TWELVE DATA QUOTE ERROR:", str(e))
        return None
def get_gold_trend_signal():
    try:
        # 1) Lấy giá Spot Gold US$/oz từ TwelveData
        gold = get_gold_ohlc()

        if not gold:
            return {
                "symbol": "XAU/USD",
                "source": "TwelveData",
                "price": 0,
                "open": 0,
                "high": 0,
                "low": 0,
                "change_pct": 0,
                "ema20": 0,
                "ema50": 0,
                "ema200": 0,
                "trend": "NO_SPOT_DATA",
                "trend_score": -1
            }

        spot_price = float(gold.get("price", 0))
        open_price = float(gold.get("open", 0))
        high = float(gold.get("high", 0))
        low = float(gold.get("low", 0))
        change_pct = float(gold.get("change_pct", 0))

        # 2) Tạm dùng Yahoo chỉ để lấy dữ liệu lịch sử tính EMA
        import yfinance as yf

        symbols = ["XAUUSD=X", "GC=F"]
        df = None
        used_history_symbol = None

        for symbol in symbols:
            try:
                temp = yf.download(
                    symbol,
                    period="90d",
                    interval="1h",
                    progress=False,
                    auto_adjust=False
                )

                if temp is not None and not temp.empty and len(temp) >= 200:
                    df = temp
                    used_history_symbol = symbol
                    break

            except Exception as inner_error:
                print(f"GOLD HISTORY ERROR {symbol}:", str(inner_error))

        if df is None or df.empty:
            return {
                "symbol": "XAU/USD",
                "source": "TwelveData",
                "history_source": "NONE",
                "price": round(spot_price, 2),
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "change_pct": round(change_pct, 2),
                "ema20": 0,
                "ema50": 0,
                "ema200": 0,
                "trend": "NO_HISTORY_DATA",
                "trend_score": 0
            }

        close = df["Close"]

        if hasattr(close, "columns"):
            close = close.iloc[:, 0]

        close = close.dropna()

        if len(close) < 200:
            return {
                "symbol": "XAU/USD",
                "source": "TwelveData",
                "history_source": used_history_symbol,
                "price": round(spot_price, 2),
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "change_pct": round(change_pct, 2),
                "ema20": 0,
                "ema50": 0,
                "ema200": 0,
                "trend": "NOT_ENOUGH_HISTORY",
                "trend_score": 0
            }

        # 3) Tính EMA từ lịch sử, nhưng dùng giá spot hiện tại để so với EMA
        ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
        ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])

        price = spot_price

        if price > ema20 > ema50 > ema200:
            trend = "STRONG_UPTREND"
            trend_score = 2

        elif price > ema20 and ema20 > ema50:
            trend = "UPTREND"
            trend_score = 1

        elif price < ema20 < ema50 < ema200:
            trend = "STRONG_DOWNTREND"
            trend_score = -2

        elif price < ema20 and ema20 < ema50:
            trend = "DOWNTREND"
            trend_score = -1

        elif price > ema20 and price < ema50:
            trend = "RECOVERY_BUT_WEAK"
            trend_score = 1

        elif price < ema20 and price > ema50:
            trend = "PULLBACK_BUT_STILL_OK"
            trend_score = -1

        else:
            trend = "SIDEWAY"
            trend_score = 0

        return {
            "symbol": "XAU/USD",
            "source": "TwelveData",
            "history_source": used_history_symbol,
            "price": round(price, 2),
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "change_pct": round(change_pct, 2),
            "ema20": round(ema20, 2),
            "ema50": round(ema50, 2),
            "ema200": round(ema200, 2),
            "trend": trend,
            "trend_score": trend_score
        }

    except Exception as e:
        print("GOLD TREND ERROR:", str(e))

        return {
            "symbol": "XAU/USD",
            "source": "TwelveData",
            "price": 0,
            "open": 0,
            "high": 0,
            "low": 0,
            "change_pct": 0,
            "ema20": 0,
            "ema50": 0,
            "ema200": 0,
            "trend": "ERROR",
            "trend_score": -1
        }
def session_report(events, state, session_name, total_score=None):
    now = datetime.now(JST)
    today = now.strftime("%Y-%m-%d")

    # Mỗi phiên chỉ gửi 1 lần / ngày
    key = f"session_report_{session_name}_{today}"

    if already_sent(state, key):
        print(f"{session_name} session already sent.")
        return

    # Giờ kết thúc phiên theo JST
    if session_name == "PHIÊN Á":
        session_end_hour = 16
    elif session_name == "PHIÊN ÂU":
        session_end_hour = 21
    elif session_name == "PHIÊN MỸ":
        session_end_hour = 23
    else:
        session_end_hour = now.hour + 6

    # News + Market
    news = get_gold_news(limit=6)

    news_score = sum(item.get("score", 0) for item in news)
    news_score = clamp_score(news_score, -4, 4)

    market_v6 = market_bias_engine(news_score)

    dollar_score = clamp_score(market_v6.get("dollar_score", 0), -4, 4)
    yield_score = clamp_score(market_v6.get("yield_score", 0), -4, 4)

    dxy_change = market_v6.get("dxy_change", 0)
    us10y_change = market_v6.get("us10y_change", 0)

    # Gold Trend
    gold_trend = get_gold_trend_signal()
    print("========== GOLD TREND ==========")
    print(gold_trend)

    trend_score = clamp_score(gold_trend.get("trend_score", 0), -4, 4)

    if total_score is None:
        total_score = clamp_score(
            news_score + dollar_score + yield_score + trend_score,
            -10,
            10
        )

    buy_prob, sell_prob = calculate_probability(total_score)

    if abs(total_score) >= 8:
        risk_level = "EXTREME"
    elif abs(total_score) >= 5:
        risk_level = "HIGH"
    elif abs(total_score) >= 3:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # Warning logic
    warnings = []

    if dollar_score <= -3 and yield_score >= 3:
        warnings.append("⚠️ DXY tăng nhưng US10Y giảm. Tín hiệu xung đột, chỉ WATCH.")
    elif dollar_score >= 3 and yield_score <= -3:
        warnings.append("⚠️ DXY giảm nhưng US10Y tăng. Tín hiệu xung đột, chỉ WATCH.")

    if gold_trend.get("trend") in ["ERROR", "NO_DATA", "NOT_ENOUGH_DATA", "TEMP_DISABLED"]:
        warnings.append("⚠️ Gold Trend chưa ổn định. Không dùng bias này để vào lệnh trực tiếp.")

    if dxy_change and dxy_change > 0.5 and total_score > 0:
        warnings.append("⚠️ DXY tăng mạnh nhưng bot vẫn BUY. Chỉ WATCH, không BUY đuổi.")

    if us10y_change and us10y_change > 0.5 and total_score > 0:
        warnings.append("⚠️ US10Y tăng mạnh nhưng bot vẫn BUY. Rủi ro SELL vàng cao.")

    # Bias label
    if total_score >= 5:
        bias = "🟢 STRONG BUY GOLD"
        action = "BUY bias mạnh. Chỉ BUY khi giá hồi về hỗ trợ và có nến xác nhận rõ."
    elif total_score >= 2:
        bias = "🟢 BUY GOLD nhẹ"
        action = "BUY bias nhẹ. Không BUY đuổi. Chỉ BUY khi giá hồi về hỗ trợ."
    elif total_score <= -5:
        bias = "🔴 STRONG SELL GOLD"
        action = "SELL bias mạnh. Chờ giá hồi lên kháng cự rồi tìm SELL theo nến xác nhận."
    elif total_score <= -2:
        bias = "🔴 SELL GOLD nhẹ"
        action = "SELL bias nhẹ. Chỉ SELL khi giá hồi lên kháng cự và có nến xác nhận."
    else:
        bias = "⚪ WAIT"
        action = "Điểm chưa đủ mạnh. Không ép lệnh."

    # Events
    session_events = []
    remaining_today_events = []
    recent_events = []

    print("===== EVENTS =====")

    for e in events:
        print(e)

        if not e.get("jst"):
            continue

        event_time = e["jst"]

        hours_passed = (now - event_time).total_seconds() / 3600
        if 0 <= hours_passed <= 36:
            recent_events.append(e)

        if event_time.date() != now.date():
            continue

        if event_time < now:
            continue

        if event_time.hour < session_end_hour:
            session_events.append(e)
        else:
            remaining_today_events.append(e)

    # Message
    msg = f"🌍 SESSION REPORT {BOT_VERSION} - {session_name}\n\n"
    msg += f"🕒 Time: {now.strftime('%m-%d %H:%M JST')}\n"
    msg += f"⚠️ Risk Level: {risk_level}\n\n"

    msg += "📊 MARKET\n"
    msg += f"DXY: {dxy_change}%\n"
    msg += f"US10Y: {us10y_change}%\n"
    msg += f"News Score: {news_score}\n"
    msg += f"Dollar Score: {dollar_score}\n"
    msg += f"Yield Score: {yield_score}\n"
    msg += f"Gold Symbol: {gold_trend.get('symbol')}\n"
    msg += f"Gold Price: {gold_trend.get('price')}\n"
    msg += f"EMA20: {gold_trend.get('ema20')}\n"
    msg += f"EMA50: {gold_trend.get('ema50')}\n"
    msg += f"EMA200: {gold_trend.get('ema200')}\n"
    msg += f"Gold Trend: {gold_trend.get('trend')}\n"
    msg += f"Trend Score: {trend_score}\n"
    msg += f"Total Score: {total_score}\n\n"

    msg += "🎯 BIAS\n"
    msg += f"{bias}\n"
    msg += f"BUY Probability: {buy_prob}%\n"
    msg += f"SELL Probability: {sell_prob}%\n\n"

    if warnings:
        msg += "⚠️ RISK CHECK\n"
        for w in warnings:
            msg += f"{w}\n"
        msg += "\n"

    msg += "🗓 TIN ẢNH HƯỞNG TRONG PHIÊN NÀY\n"
    if not session_events:
        msg += "Không có tin USD quan trọng trong phiên này.\n\n"
    else:
        for e in session_events[:5]:
            msg += f"- {e['title']} | {e['jst'].strftime('%H:%M JST')}\n"
            msg += f"  Forecast: {e['forecast']} | Previous: {e['previous']} | Actual: {e['actual']}\n"

    msg += "\n📌 TIN CÒN LẠI TRONG NGÀY\n"
    if not remaining_today_events:
        msg += "Không còn tin USD quan trọng sau phiên này.\n\n"
    else:
        for e in remaining_today_events[:5]:
            msg += f"- {e['title']} | {e['jst'].strftime('%H:%M JST')}\n"
            msg += f"  Forecast: {e['forecast']} | Previous: {e['previous']} | Actual: {e['actual']}\n"

    msg += "\n🔥 TIN 36 GIỜ GẦN NHẤT / DƯ ÂM\n"
    if not recent_events:
        msg += "Không có tin lớn trong 36 giờ qua.\n\n"
    else:
        for e in recent_events[:5]:
            passed = int((now - e["jst"]).total_seconds() / 3600)
            msg += f"- {e['title']} | {e['jst'].strftime('%m-%d %H:%M JST')} | {passed}h trước\n"

        msg += "\n👉 Các tin trên vẫn có thể tạo dư âm cho USD, US10Y và vàng.\n\n"

    msg += "\n📌 KỊCH BẢN PHIÊN\n"
    msg += action
    msg += "\n\n⚠️ Đây là báo cáo phiên, không phải lệnh vào trực tiếp."

    send_telegram(msg)
    mark_sent(state, key)
def daily_gold_bias(events, state, force=False):
    now = datetime.now(JST)

    if now.weekday() in [5, 6]:

        today = now.strftime("%Y-%m-%d")
        weekend_key = f"weekend_notice_{today}"

        if not already_sent(state, weekend_key):

            send_telegram(
                "📅 CUỐI TUẦN\n\n"
                "Forex và thị trường vàng quốc tế đã đóng cửa.\n"
                "Không phát sinh lịch USD High Impact mới.\n"
                "Bot tạm nghỉ đến thứ Hai."
            )

            mark_sent(state, weekend_key)

        return
    now = datetime.now(JST)
    today = now.strftime("%Y-%m-%d")
    key = f"daily_gold_bias_{today}"

    if not force and already_sent(state, key):
        print("Daily gold bias already sent.")
        return

    selected_events = target_events(events)
    print("SELECTED EVENTS:")
    print(selected_events)
    news = get_gold_news(limit=6)

    economic_score = 0
    news_score = 0
    fomc_risk = False

    fomc_news_score = score_fomc_from_news(news)

    for e in selected_events:
        bias, score = gold_bias_from_event(
            e["title"],
            e["actual"],
            e["forecast"]
        )

        economic_score += score

        title_l = e["title"].lower()
        if (
            "fomc" in title_l
            or "federal funds" in title_l
            or "powell" in title_l
        ):
            fomc_risk = True

    for item in news:
        news_score += item.get("score", 0)

    if fomc_risk and economic_score == 0:
        economic_score += fomc_news_score

    economic_score = clamp_score(economic_score)
    news_score = clamp_score(news_score)

    market_v6 = market_bias_engine(news_score)

    dollar_score = clamp_score(market_v6.get("dollar_score", 0))
    yield_score = clamp_score(market_v6.get("yield_score", 0))
    gold_trend = get_gold_trend_signal()
    trend_score = clamp_score(
        gold_trend.get("trend_score", 0)
    )

    dxy_change = market_v6.get("dxy_change", 0)
    us10y_change = market_v6.get("us10y_change", 0)

    total_score = (
        economic_score
        + news_score
        + dollar_score
        + yield_score
        + trend_score
    )
    total_score = clamp_score(total_score, -10, 10)
    conflict_warning = ""

    if dollar_score <= -3 and yield_score >= 3:
        conflict_warning = "⚠️ DXY tăng mạnh nhưng US10Y giảm mạnh. Tín hiệu đang xung đột, chỉ nên WATCH, không ép lệnh.\n\n"

    elif dollar_score >= 3 and yield_score <= -3:
        conflict_warning = "⚠️ DXY giảm mạnh nhưng US10Y tăng mạnh. Tín hiệu đang xung đột, chỉ nên WATCH, không ép lệnh.\n\n"

    if now.hour == 15 and now.minute < 15:
        session_report(events, state, "TEST")

    buy_prob, sell_prob = calculate_probability(total_score)
    confidence = max(buy_prob, sell_prob)

    if fomc_risk:
        risk_level = "VERY HIGH"
    elif abs(total_score) >= 5:
        risk_level = "HIGH"
    elif abs(total_score) >= 3:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    if total_score >= 5:
        primary_bias = "BUY GOLD BIAS"
        bias_icon = "🟢"
        action = "🟢 ACTION: STRONG BUY ZONE"
        scenario = "Kịch bản ưu tiên: BUY bias mạnh. Chờ giá hồi về hỗ trợ rồi tìm BUY theo nến xác nhận.\n"

    elif total_score >= 2:
        primary_bias = "BUY GOLD nhẹ"
        bias_icon = "🟢"
        action = "🟢 ACTION: BUY WATCH"
        scenario = "Kịch bản ưu tiên: BUY bias nhẹ. Chỉ BUY khi giá hồi về hỗ trợ và có nến xác nhận.\n"

    elif total_score <= -5:
        primary_bias = "SELL GOLD BIAS"
        bias_icon = "🔴"
        action = "🔴 ACTION: STRONG SELL ZONE"
        scenario = "Kịch bản ưu tiên: SELL bias mạnh. Chờ giá hồi lên kháng cự rồi tìm SELL theo nến xác nhận.\n"

    elif total_score <= -2:
        primary_bias = "SELL GOLD nhẹ"
        bias_icon = "🔴"
        action = "🔴 ACTION: SELL WATCH"
        scenario = "Kịch bản ưu tiên: SELL bias nhẹ. Chỉ SELL khi giá hồi lên kháng cự và có nến xác nhận.\n"

    else:
        primary_bias = "WAIT / chưa rõ"
        bias_icon = "⚪"
        action = "⚪ ACTION: WAIT"
        scenario = "Kịch bản ưu tiên: WAIT. Điểm chưa đủ mạnh, không ép lệnh.\n"

    msg = f"📊 GOLD DAILY INTELLIGENCE {BOT_VERSION}\n\n"
    msg += f"🕒 Time: {now.strftime('%m-%d %H:%M JST')}\n"
    msg += f"⚠️ Risk Level: {risk_level}\n\n"
    msg += "══════════════════════\n\n"

    msg += "1️⃣ HIGH IMPACT EVENTS\n\n"

    if not selected_events:
        msg += "⚪ Không có tin USD High Impact quan trọng trong khung gần.\n\n"
    else:
        for e in selected_events:
            bias, score = gold_bias_from_event(
                e["title"],
                e["actual"],
                e["forecast"]
            )

            event_time = "-"
            if e.get("jst"):
                event_time = e["jst"].strftime("%m-%d %H:%M JST")

            msg += f"🇺🇸 {e['title']}\n"
            msg += f"Time: {event_time}\n"
            msg += f"Forecast: {e['forecast']} | Previous: {e['previous']} | Actual: {e['actual']}\n"
            msg += f"Impact: {bias}\n"
            msg += f"Score: {score}\n\n"

    msg += "══════════════════════\n\n"
    msg += "2️⃣ GOLD MARKET NEWS\n\n"

    if not news:
        msg += "⚪ Chưa lấy được headline mới.\n\n"
    else:
        for item in news[:5]:
            score = item.get("score", 0)

            if score > 0:
                icon = "🟢"
                impact = "Bullish Gold"
            elif score < 0:
                icon = "🔴"
                impact = "Bearish Gold"
            else:
                icon = "⚪"
                impact = "Neutral"

            title_show = item.get("vi_title", item.get("title", ""))
            source = item.get("source", "")

            msg += f"{icon} {title_show}\n"
            if source:
                msg += f"Nguồn: {source}\n"
            msg += f"Impact: {impact}\n\n"

    msg += "══════════════════════\n\n"
    msg += "3️⃣ MARKET BIAS ENGINE\n\n"
    msg += f"Economic Score: {economic_score}\n"
    msg += f"News Score: {news_score}\n"
    msg += f"Dollar Score: {dollar_score}\n"
    msg += f"Yield Score: {yield_score}\n"
    msg += f"Trend Score: {trend_score}\n"
    msg += f"Gold Trend: {gold_trend.get('trend')}\n"
    msg += f"Gold Price: {gold_trend.get('price')}\n"
    msg += f"EMA20: {gold_trend.get('ema20')}\n"
    msg += f"EMA50: {gold_trend.get('ema50')}\n"
    msg += f"EMA200: {gold_trend.get('ema200')}\n"
    msg += f"DXY Change: {dxy_change}%\n"
    msg += f"US10Y Change: {us10y_change}%\n"
    msg += f"Total Gold Score: {total_score}\n\n"
    msg += f"🎯 Confidence: {confidence}%\n"
    msg += f"🟢 BUY Probability: {buy_prob}%\n"
    msg += f"🔴 SELL Probability: {sell_prob}%\n"
    msg += f"{action}\n\n"
    msg += conflict_warning
    msg += "══════════════════════\n\n"
    msg += "4️⃣ TODAY BIAS\n\n"
    msg += f"{bias_icon} Primary Bias: {primary_bias}\n\n"

    if fomc_risk:
        msg += "Kịch bản FOMC:\n"
        msg += "- Trước / trong FOMC: ưu tiên WAIT, không ép lệnh.\n"
        msg += "- Chỉ giao dịch sau khi giá phản ứng rõ với tin.\n\n"

    msg += scenario

    msg += "\n══════════════════════\n"
    msg += "⚠️ Đây là mô hình bias, không phải lệnh vào trực tiếp.\n"
    msg += "Cần thêm phản ứng giá, spread và nến xác nhận."

    last_score_key = "last_daily_total_score"
    last_total_score = state.get(last_score_key)

    if not force and last_total_score == total_score:
        print("Daily score unchanged, skip telegram")
        mark_sent(state, key)
        return

    send_telegram(msg)

    check_bias_reversal(state, total_score)

    state[last_score_key] = total_score
    mark_sent(state, key)
def check_events(events, state):

    now = datetime.now(JST)
    sent_any = False

    for e in events:

        if not e["jst"]:
            continue

        minutes = (e["jst"] - now).total_seconds() / 60
        key_base = event_key(e)

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

        if e["actual"] != "-" and -30 <= minutes <= 30:
            print("ACTUAL DETECTED")
            print(e)
            key = f"actual_{key_base}_{e['actual']}"

            if not already_sent(state, key):
                bias, news_score = gold_bias_from_event(
                    e["title"],
                    e["actual"],
                    e["forecast"]
                )

                market_v6 = market_bias_engine(news_score)
                msg = format_actual_alert(e, market_v6)

                send_telegram(msg)
                mark_sent(state, key)
                sent_any = True

    if not sent_any:
        print("No alert to send now.")
def check_bias_reversal(state, total_score):

    last_score = state.get("last_bias_score")

    if last_score is None:
        state["last_bias_score"] = total_score
        return

    if last_score <= -3 and total_score >= 3:

        send_telegram(
            "🚨 BIAS REVERSAL\n\n"
            "SELL ➜ BUY\n"
            f"Old Score: {last_score}\n"
            f"New Score: {total_score}"
        )

    elif last_score >= 3 and total_score <= -3:

        send_telegram(
            "🚨 BIAS REVERSAL\n\n"
            "BUY ➜ SELL\n"
            f"Old Score: {last_score}\n"
            f"New Score: {total_score}"
        )

    state["last_bias_score"] = total_score       
def manual_test(events, state):
    session_report(events, state, "TEST TREND")

    spot_price = get_gold_spot_price()
    send_telegram(f"🧪 GOLD US/OZ TEST\n\nPrice: {spot_price}")

    send_telegram(
        f"🧪 TWELVE DATA KEY TEST\n\nKey exists: {bool(TWELVE_DATA_API_KEY)}"
    )

    gold_quote = get_gold_ohlc()
    send_telegram(f"🧪 GOLD QUOTE TEST\n\n{gold_quote}")

    gold_trend = get_gold_trend_signal()
    plan = build_trade_plan(gold_trend, 5)
    trade_msg = format_trade_plan(gold_trend, plan)
    send_telegram(trade_msg)

    msg = "✅ BOT TEST OK\n\n"
    msg += f"MODE: {MODE}\n"
    msg += f"Time: {datetime.now(JST).strftime('%m-%d %H:%M JST')}\n"
    msg += f"Events found: {len(events)}\n\n"
    msg += "Telegram + GitHub Actions đang hoạt động."

    send_telegram(msg)

def main():
    state = load_state()
    events = get_events()
    now = datetime.now(JST)
    if now.weekday() in [5, 6]:
        print("WEEKEND DETECTED")

        today = now.strftime("%Y-%m-%d")
        weekend_key = f"weekend_notice_{today}"

        if not already_sent(state, weekend_key):
            send_telegram(
                "📅 CUỐI TUẦN\n\n"
                "Forex và thị trường vàng quốc tế đã đóng cửa.\n"
                "Không phát sinh lịch USD High Impact mới.\n"
                "Bot tạm nghỉ đến thứ Hai."
            )
            mark_sent(state, weekend_key)
            save_state(state)
        else:
            print("Weekend notice already sent.")

        return

    print(f"MODE={MODE}")
    print(f"EVENTS_FOUND={len(events)}")
    print(f"NOW_JST={now.strftime('%Y-%m-%d %H:%M:%S')}")

    # TEST MODE
    if MODE == "test":
        manual_test(events, state)
        save_state(state)
        return

    # AUTO MODE
    elif MODE == "auto":
        print("AUTO MODE START")

        daily_gold_bias(events, state, force=False)

        check_events(events, state)

        # Báo cáo đầu ngày
        if now.hour == 7 and now.minute < 15:
            daily_report(events, state)
        if now.hour == 7 and now.minute < 15:
            daily_all_events_report(state)

        # Báo cáo phiên Á
        if now.hour == 9 and now.minute < 45:
            session_report(events, state, "PHIÊN Á")

        # Báo cáo phiên Âu
        if now.hour == 16 and now.minute < 45:
            session_report(events, state, "PHIÊN ÂU")

        # Báo cáo phiên Mỹ
        if now.hour == 21 and now.minute < 45:
           session_report(events, state, "PHIÊN MỸ")

        # Cập nhật tin vàng trong ngày
        if now.hour in [9, 13, 17] and now.minute < 15:
            gold_news_update(state)

    elif MODE == "daily":
        daily_report(events, state)

    elif MODE == "check":
        check_events(events, state)

    elif MODE == "news":
        gold_news_update(state)

    elif MODE == "bias":
        daily_gold_bias(events, state, force=True)

    else:
        send_telegram(f"❌ Unknown MODE: {MODE}")

    save_state(state)

try:
    main()

except Exception as e:
    print("ERROR:", str(e))

    try:
        send_telegram(f"❌ GOLD BOT ERROR\n\n{e}")

    except Exception as send_error:
        print("FAILED TO SEND ERROR:", str(send_error))
            
