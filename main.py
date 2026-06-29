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

def calculate_support_resistance(gold_trend):

    return {
        "support": gold_trend["support"],
        "resistance": gold_trend["resistance"],
        "mid": round(
            (gold_trend["support"] + gold_trend["resistance"]) / 2,
            2
        ),
        "status":"OK"
    }
def get_session_score():
    now = datetime.now(JST)
    hour = now.hour

    # Giờ Nhật
    if 7 <= hour < 15:
        return {
            "session": "TOKYO",
            "score": 0,
            "note": "Phiên Á: biến động thường yếu, không ép lệnh."
        }

    elif 15 <= hour < 21:
        return {
            "session": "LONDON",
            "score": 1,
            "note": "Phiên Âu: biến động tốt hơn, có thể tìm setup."
        }

    elif 21 <= hour <= 23 or 0 <= hour < 2:
        return {
            "session": "NEW_YORK",
            "score": 2,
            "note": "Phiên Mỹ: biến động mạnh, ưu tiên setup rõ."
        }

    else:
        return {
            "session": "LOW_LIQUIDITY",
            "score": -2,
            "note": "Thanh khoản thấp. Tránh giữ lệnh hoặc mở lệnh mới."
        }
def get_momentum_score(gold_trend):
    try:
        import yfinance as yf

        symbols = ["XAUUSD=X", "GC=F"]
        df = None

        for symbol in symbols:
            temp = yf.download(
                symbol,
                period="5d",
                interval="15m",
                progress=False,
                auto_adjust=False
            )

            if temp is not None and not temp.empty and len(temp) >= 30:
                df = temp
                break

        if df is None or df.empty:
            return {
                "momentum_score": 0,
                "momentum": "NO_DATA",
                "momentum_note": "Không có dữ liệu M15."
            }

        open_ = df["Open"]
        high = df["High"]
        low = df["Low"]
        close = df["Close"]

        if hasattr(open_, "columns"):
            open_ = open_.iloc[:, 0]
        if hasattr(high, "columns"):
            high = high.iloc[:, 0]
        if hasattr(low, "columns"):
            low = low.iloc[:, 0]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]

        last_open = float(open_.iloc[-1])
        last_high = float(high.iloc[-1])
        last_low = float(low.iloc[-1])
        last_close = float(close.iloc[-1])

        prev_close_1 = float(close.iloc[-2])
        prev_close_2 = float(close.iloc[-3])

        candle_range = last_high - last_low
        candle_body = abs(last_close - last_open)

        if candle_range <= 0:
            return {
                "momentum_score": 0,
                "momentum": "NO_RANGE",
                "momentum_note": "Nến không có biên độ."
            }

        body_ratio = candle_body / candle_range
        close_position = (last_close - last_low) / candle_range

        recent_high = float(high.tail(20).max())
        recent_low = float(low.tail(20).min())

        score = 0
        notes = []

        # BUY momentum
        if last_close > last_open:
            score += 1
            notes.append("Nến cuối xanh")

        if last_close > prev_close_1 > prev_close_2:
            score += 1
            notes.append("3 nến tăng liên tiếp")

        if close_position >= 0.70 and body_ratio >= 0.50:
            score += 1
            notes.append("Đóng cửa gần đỉnh nến")

        if last_close >= recent_high * 0.999:
            score += 1
            notes.append("Giá gần phá high 20 nến")

        # SELL momentum
        if last_close < last_open:
            score -= 1
            notes.append("Nến cuối đỏ")

        if last_close < prev_close_1 < prev_close_2:
            score -= 1
            notes.append("3 nến giảm liên tiếp")

        if close_position <= 0.30 and body_ratio >= 0.50:
            score -= 1
            notes.append("Đóng cửa gần đáy nến")

        if last_close <= recent_low * 1.001:
            score -= 1
            notes.append("Giá gần phá low 20 nến")

        score = clamp_score(score, -3, 3)

        if score >= 2:
            momentum = "BULLISH"
        elif score <= -2:
            momentum = "BEARISH"
        else:
            momentum = "NEUTRAL"

        return {
            "momentum_score": score,
            "momentum": momentum,
            "momentum_note": ", ".join(notes) if notes else "Momentum trung tính."
        }

    except Exception as e:
        print("MOMENTUM ERROR:", str(e))
        return {
            "momentum_score": 0,
            "momentum": "ERROR",
            "momentum_note": str(e)
        }
def score_to_probability(final_score):
    if final_score >= 10:
        return 90
    elif final_score >= 8:
        return 85
    elif final_score >= 6:
        return 78
    elif final_score >= 4:
        return 68
    elif final_score >= 2:
        return 58
    elif final_score <= -10:
        return 90
    elif final_score <= -8:
        return 85
    elif final_score <= -6:
        return 78
    elif final_score <= -4:
        return 68
    elif final_score <= -2:
        return 58
    else:
        return 50


def probability_label(probability):
    if probability >= 85:
        return "VERY_HIGH"
    elif probability >= 75:
        return "HIGH"
    elif probability >= 65:
        return "MEDIUM"
    elif probability >= 55:
        return "LOW"
    else:
        return "WAIT"
def evaluate_price_location(gold_trend):
    price = float(gold_trend.get("price", 0))
    support = float(gold_trend.get("support", 0))
    resistance = float(gold_trend.get("resistance", 0))

    width = resistance - support

    if price <= 0 or support <= 0 or resistance <= 0 or width <= 0:
        return {
            "location": "UNKNOWN",
            "score": 0,
            "distance_to_support": 0,
            "distance_to_resistance": 0,
            "breakout_risk": "UNKNOWN"
        }

    distance_to_support = round(abs(price - support), 2)
    distance_to_resistance = round(abs(resistance - price), 2)

    pos = (price - support) / width

    if pos < 0.2:
        location = "NEAR_SUPPORT"
        score = 2
    elif pos < 0.4:
        location = "LOW_RANGE"
        score = 1
    elif pos < 0.6:
        location = "MIDDLE"
        score = 0
    elif pos < 0.8:
        location = "HIGH_RANGE"
        score = -1
    else:
        location = "NEAR_RESISTANCE"
        score = -2

    if distance_to_resistance <= 10:
        breakout_risk = "HIGH"
    elif distance_to_resistance <= 20:
        breakout_risk = "MEDIUM"
    else:
        breakout_risk = "LOW"

    return {
        "location": location,
        "score": score,
        "distance_to_support": distance_to_support,
        "distance_to_resistance": distance_to_resistance,
        "breakout_risk": breakout_risk
    }
def classify_trend_bias(trend):
    bullish_trends = [
        "STRONG_UPTREND",
        "UPTREND",
        "PULLBACK_BUT_STILL_OK"
    ]

    bearish_trends = [
        "STRONG_DOWNTREND",
        "DOWNTREND"
    ]

    weak_trends = [
        "RECOVERY_BUT_WEAK",
        "SIDEWAY",
        "NO_DATA",
        "NO_SPOT_DATA",
        "NO_HISTORY_DATA",
        "NOT_ENOUGH_HISTORY",
        "ERROR"
    ]

    if trend in bullish_trends:
        return "BULLISH"

    if trend in bearish_trends:
        return "BEARISH"

    if trend in weak_trends:
        return "NEUTRAL"

    return "NEUTRAL"
def build_score_engine(gold_trend, news_score=0, dollar_score=0, yield_score=0):

    price = float(gold_trend.get("price", 0))
    high = float(gold_trend.get("high", 0))
    low = float(gold_trend.get("low", 0))

    support = float(gold_trend.get("support", 0))
    resistance = float(gold_trend.get("resistance", 0))

    trend = gold_trend.get("trend", "SIDEWAY")
    trend_bias = classify_trend_bias(trend)

    adx = float(gold_trend.get("adx", 0))
    atr = float(gold_trend.get("atr", 0))

    ema_score = 0
    adx_score = 0
    fib_score = 0
    sr_score = 0
    volatility_score = 0

    # =========================
    # 1. TREND
    # =========================

    trend_table = {
        "STRONG_UPTREND": 4,
        "UPTREND": 3,
        "PULLBACK_BUT_STILL_OK": 2,
        "SIDEWAY": 0,
        "DOWNTREND": -3,
        "STRONG_DOWNTREND": -4
    }

    ema_score = trend_table.get(trend, 0)

    # =========================
    # 2. ADX
    # =========================

    if adx >= 35:
        adx_power = 3
    elif adx >= 30:
        adx_power = 2
    elif adx >= 25:
        adx_power = 1
    else:
        adx_power = 0

    if trend_bias == "BULLISH":
        adx_score = adx_power
    elif trend_bias == "BEARISH":
        adx_score = -adx_power
    else:
        adx_score = 0

    # =========================
    # 3. Fibonacci
    # =========================

    if high > low:

        fib = calculate_fibonacci(high, low)

        fib382 = fib["fib382"]
        fib500 = fib["fib500"]
        fib618 = fib["fib618"]

        if trend_bias == "BULLISH":

            if fib500 <= price <= fib382:
                fib_score = 2

            elif price >= fib382:
                fib_score = 1

        elif trend_bias == "BEARISH":

            if fib500 <= price <= fib618:
                fib_score = -2

            elif price <= fib618:
                fib_score = -1

    # =========================
    # 4. Support Resistance
    # =========================

    distance_support = abs(price-support)
    distance_resistance = abs(resistance-price)

    if trend_bias == "BULLISH":

        if distance_support < distance_resistance:
            sr_score = 2

    elif trend_bias == "BEARISH":

        if distance_resistance < distance_support:
            sr_score = -2

    # =========================
    # 5. ATR
    # =========================

    if price > 0:

        atr_pct = atr / price

        if 0.002 <= atr_pct <= 0.007:
            volatility_score = 1

        elif atr_pct > 0.012:
            volatility_score = -1

    # =========================
    # 6. Session
    # =========================

    session = get_session_score()

    session_score = session["score"]

    # =========================
    # 7. Momentum
    # =========================

    momentum = get_momentum_score(gold_trend)

    momentum_score = momentum["momentum_score"]

    # =========================
    # 8. Location
    # =========================

    location = evaluate_price_location(gold_trend)

    location_score = location["score"]

    # =========================
    # 9. External
    # =========================

    news_score = clamp_score(news_score,-3,3)
    dollar_score = clamp_score(dollar_score,-2,2)
    yield_score = clamp_score(yield_score,-2,2)

    # =========================
    # 10. Final Score
    # =========================

    final_score = (

        ema_score

        + adx_score

        + fib_score

        + sr_score

        + volatility_score

        + session_score

        + momentum_score

        + location_score

        + news_score

        + dollar_score

        + yield_score

    )

    final_score = clamp_score(final_score,-12,12)

    probability = score_to_probability(final_score)

    confidence = probability_label(probability)

    print("========== SCORE ==========")
    print("Trend:",trend)
    print("Trend Bias:",trend_bias)
    print("EMA:",ema_score)
    print("ADX:",adx_score)
    print("FIB:",fib_score)
    print("SR:",sr_score)
    print("Momentum:",momentum_score)
    print("Location:",location_score)
    print("News:",news_score)
    print("Dollar:",dollar_score)
    print("Yield:",yield_score)
    print("FINAL:",final_score)
    print("===========================")

    return {

        "trend_score":ema_score,

        "trend_bias":trend_bias,

        "adx_score":adx_score,

        "fib_score":fib_score,

        "sr_score":sr_score,

        "volatility_score":volatility_score,

        "news_score":news_score,

        "dollar_score":dollar_score,

        "yield_score":yield_score,

        "session":session["session"],

        "session_score":session_score,

        "session_note":session["note"],

        "momentum":momentum["momentum"],

        "momentum_score":momentum_score,

        "momentum_note":momentum["momentum_note"],

        "price_location":location["location"],

        "location_score":location_score,

        "distance_to_support":location["distance_to_support"],

        "distance_to_resistance":location["distance_to_resistance"],

        "breakout_risk":location["breakout_risk"],

        "final_score":final_score,

        "probability":probability,

        "confidence":confidence

    }
def format_score_engine(score):

    msg = "🧠 SCORE ENGINE\n"

    msg += f"EMA Trend Score: {score.get('trend_score')}\n"
    msg += f"ADX Score: {score.get('adx_score')}\n"
    msg += f"Fibonacci Score: {score.get('fib_score')}\n"
    msg += f"Support/Resistance Score: {score.get('sr_score')}\n"
    msg += f"Volatility Score: {score.get('volatility_score')}\n"

    msg += f"News Score: {score.get('news_score')}\n"
    msg += f"Dollar Score: {score.get('dollar_score')}\n"
    msg += f"Yield Score: {score.get('yield_score')}\n"
    msg += f"Price Location: {score.get('price_location')}\n"
    msg += f"Location Score: {score.get('location_score')}\n"
    msg += f"Distance To Support: {score.get('distance_to_support')}\n"
    msg += f"Distance To Resistance: {score.get('distance_to_resistance')}\n"
    msg += f"Breakout Risk: {score.get('breakout_risk')}\n"

    msg += "--------------------\n"

    msg += f"Momentum: {score.get('momentum')}\n"
    msg += f"Momentum Score: {score.get('momentum_score')}\n"

    msg += f"Session: {score.get('session')}\n"
    msg += f"Session Score: {score.get('session_score')}\n"

    msg += "--------------------\n"

    msg += f"Probability: {score.get('probability')}%\n"
    msg += f"Confidence: {score.get('confidence')}\n"

    msg += "--------------------\n"

    msg += f"Final Score: {score.get('final_score')}\n"

    return msg
def find_swings(df):
    highs = df["High"]
    lows = df["Low"]

    if hasattr(highs, "columns"):
        highs = highs.iloc[:, 0]

    if hasattr(lows, "columns"):
        lows = lows.iloc[:, 0]

    # 24 nến H1 gần nhất ≈ 1 ngày giao dịch
    lookback = 24

    recent_highs = highs.tail(lookback).dropna()
    recent_lows = lows.tail(lookback).dropna()

    if len(recent_highs) == 0 or len(recent_lows) == 0:
        return 0, 0

    resistance = float(recent_highs.max())
    support = float(recent_lows.min())

    return support, resistance
def calculate_score_engine(gold):
    score = 0

    detail = {}

    # EMA
    ema_score = gold.get("trend_score", 0)
    score += ema_score
    detail["ema"] = ema_score

    # ADX
    adx = gold.get("adx", 0)

    if adx >= 30:
        adx_score = 2
    elif adx >= 25:
        adx_score = 1
    else:
        adx_score = 0

    if ema_score < 0:
        score -= adx_score
        detail["adx"] = -adx_score

    elif ema_score > 0:
        score += adx_score
        detail["adx"] = adx_score

    else:
        detail["adx"] = 0

    # Fibonacci
    fib50 = gold.get("fib50", 0)
    price = gold.get("price", 0)

    fib_score = 0

    if abs(price - fib50) < 5:
        if ema_score > 0:
            fib_score = 1
        elif ema_score < 0:
            fib_score = -1

    score += fib_score
    detail["fib"] = fib_score

    # Support Resistance
    sr_score = 0

    support = gold.get("support", 0)
    resistance = gold.get("resistance", 0)

    if ema_score > 0:

        if abs(price-support) < 5:
            sr_score = 2

    elif ema_score < 0:

        if abs(price-resistance) < 5:
            sr_score = -2

    score += sr_score
    detail["sr"] = sr_score

    detail["total"] = score

    return detail
def apply_trade_filters(plan, gold_trend, score):
    direction = plan.get("direction", "WAIT")
    status = plan.get("status", "WAIT")

    if direction == "WAIT":
        return plan

    if status == "WAIT_PULLBACK":
        return plan

    rr = plan.get("rr", "-")
    try:
        rr_value = float(rr)
    except:
        rr_value = 0

    adx = float(gold_trend.get("adx", 0))
    trend = gold_trend.get("trend", "SIDEWAY")
    probability = int(score.get("probability", 50))
    momentum = score.get("momentum", "NEUTRAL")
    session = score.get("session", "UNKNOWN")
    price_location = score.get("price_location", "UNKNOWN")
    distance_to_resistance = float(score.get("distance_to_resistance", 999))
    distance_to_support = float(score.get("distance_to_support", 999))
    block_reasons = []

    if rr_value < 1.5:
        block_reasons.append(f"RR thấp ({rr_value}). Tối thiểu cần 1.5.")

    if adx < 20:
        block_reasons.append(f"ADX yếu ({adx}). Xu hướng chưa đủ lực.")

    if probability < 60:
        block_reasons.append(f"Probability thấp ({probability}%). Không đủ lợi thế.")

    if direction == "BUY" and momentum == "BEARISH":
        block_reasons.append("Momentum BEARISH xung đột với BUY.")

    if direction == "SELL" and momentum == "BULLISH":
        block_reasons.append("Momentum BULLISH xung đột với SELL.")

    if session == "LOW_LIQUIDITY":
        block_reasons.append("Phiên thanh khoản thấp.")

    if trend in ["SIDEWAY", "RECOVERY_BUT_WEAK", "PULLBACK_BUT_STILL_OK"] and probability < 75:
        block_reasons.append(f"Trend chưa rõ ({trend}) và Probability chưa đủ cao.")
    if direction == "BUY" and price_location == "NEAR_RESISTANCE":
        block_reasons.append(
            f"BUY sát Resistance. Còn cách kháng cự {distance_to_resistance} giá."
        )

    if direction == "SELL" and price_location == "NEAR_SUPPORT":
        block_reasons.append(
            f"SELL sát Support. Còn cách hỗ trợ {distance_to_support} giá."
        )

    if direction == "BUY" and distance_to_resistance < 15:
         block_reasons.append(
             f"Khoảng cách tới Resistance quá gần ({distance_to_resistance}). BUY không đáng RR."
        )

    if direction == "SELL" and distance_to_support < 15:
         block_reasons.append(
             f"Khoảng cách tới Support quá gần ({distance_to_support}). SELL không đáng RR."
         )
    if block_reasons:
        return {
            "status": "NO_TRADE",
            "direction": "WAIT",
            "entry": "-",
            "sl": "-",
            "tp1": "-",
            "tp2": "-",
            "tp3": "-",
            "rr": "-",
            "note": "NO TRADE. " + " ".join(block_reasons)
        }

    return plan
def build_trade_plan(gold_trend, total_score):
    price = float(gold_trend.get("price", 0))
    high = float(gold_trend.get("high", 0))
    low = float(gold_trend.get("low", 0))
    atr = float(gold_trend.get("atr", 0))
    trend = gold_trend.get("trend", "SIDEWAY")

    status = "WAIT"

    if price <= 0:
        return {
            "status": "WAIT",
            "direction": "WAIT",
            "entry": "-",
            "sl": "-",
            "tp1": "-",
            "tp2": "-",
            "tp3": "-",
            "rr": "-",
            "note": "Không có giá XAU/USD hợp lệ."
        }

    fib = calculate_fibonacci(high, low)
    fib382 = float(fib["fib382"])
    fib500 = float(fib["fib500"])
    fib618 = float(fib["fib618"])

    sr = calculate_support_resistance(gold_trend)
    support = float(sr.get("support", low))
    resistance = float(sr.get("resistance", high))

    if atr <= 0:
        day_range = high - low
        if day_range <= 0:
            day_range = price * 0.003
        atr = max(day_range * 0.25, price * 0.0015)

    final_score = total_score

    if trend == "STRONG_DOWNTREND":
        final_score = min(final_score, -5)
    elif trend == "STRONG_UPTREND":
        final_score = max(final_score, 5)

    # ======================
    # BUY INTRADAY
    # ======================
    if final_score >= 5:
        direction = "BUY"

        entry_low = price - atr * 0.45
        entry_high = price - atr * 0.20

        if fib618 < price:
            entry_low = min(entry_low, fib618)
        if fib500 < price:
            entry_high = max(entry_high, fib500)

        entry_width = entry_high - entry_low
        max_width = atr * 0.35

        if entry_width > max_width:
            entry_mid_temp = (entry_low + entry_high) / 2
            entry_low = entry_mid_temp - max_width / 2
            entry_high = entry_mid_temp + max_width / 2

        entry_mid = (entry_low + entry_high) / 2

        sl = min(support - atr * 0.15, entry_low - atr * 0.45)

        tp1 = entry_mid + atr * 0.55
        tp2 = min(resistance, entry_mid + atr * 1.00)
        tp3 = min(resistance + atr * 0.35, entry_mid + atr * 1.45)

        note = (
            f"BUY intraday mạnh. Final Score: {final_score}. "
            "Không BUY đuổi. Chỉ BUY khi giá hồi về entry, có nến xác nhận. "
            "Không giữ lệnh qua đêm."
        )

    elif final_score >= 2:
        direction = "BUY"

        entry_low = price - atr * 0.35
        entry_high = price - atr * 0.15

        entry_mid = (entry_low + entry_high) / 2

        sl = min(support - atr * 0.10, entry_low - atr * 0.40)

        tp1 = entry_mid + atr * 0.45
        tp2 = min(resistance, entry_mid + atr * 0.80)
        tp3 = min(resistance + atr * 0.20, entry_mid + atr * 1.15)

        note = (
            f"BUY intraday nhẹ. Final Score: {final_score}. "
            "Chỉ BUY khi hồi xuống entry và có nến xác nhận. Không giữ qua đêm."
        )

    # ======================
    # SELL INTRADAY
    # ======================
    elif final_score <= -5:
        direction = "SELL"

        entry_low = price + atr * 0.20
        entry_high = price + atr * 0.45

        if fib618 > price:
            entry_low = min(entry_low, fib618)
        if fib500 > price:
            entry_high = max(entry_high, fib500)

        entry_width = entry_high - entry_low
        max_width = atr * 0.35

        if entry_width > max_width:
            entry_mid_temp = (entry_low + entry_high) / 2
            entry_low = entry_mid_temp - max_width / 2
            entry_high = entry_mid_temp + max_width / 2

        entry_mid = (entry_low + entry_high) / 2

        sl = max(resistance + atr * 0.15, entry_high + atr * 0.45)

        tp1 = entry_mid - atr * 0.55
        tp2 = max(support, entry_mid - atr * 1.00)
        tp3 = max(support - atr * 0.35, entry_mid - atr * 1.45)

        note = (
            f"SELL intraday mạnh. Final Score: {final_score}. "
            "Không SELL đuổi. Chỉ SELL khi giá hồi lên entry, có nến xác nhận. "
            "Không giữ lệnh qua đêm."
        )

    elif final_score <= -2:
        direction = "SELL"

        entry_low = price + atr * 0.15
        entry_high = price + atr * 0.35

        entry_mid = (entry_low + entry_high) / 2

        sl = max(resistance + atr * 0.10, entry_high + atr * 0.40)

        tp1 = entry_mid - atr * 0.45
        tp2 = max(support, entry_mid - atr * 0.80)
        tp3 = max(support - atr * 0.20, entry_mid - atr * 1.15)

        note = (
            f"SELL intraday nhẹ. Final Score: {final_score}. "
            "Chỉ SELL khi hồi lên entry và có nến xác nhận. Không giữ qua đêm."
        )

    else:
        return {
            "status": "WAIT",
            "direction": "WAIT",
            "entry": "-",
            "sl": "-",
            "tp1": "-",
            "tp2": "-",
            "tp3": "-",
            "rr": "-",
            "note": (
                f"WAIT. Final Score: {final_score}. "
                "Điểm chưa đủ mạnh hoặc tín hiệu xung đột. Không vào lệnh."
            )
        }

    entry_low = round(entry_low, 2)
    entry_high = round(entry_high, 2)
    entry_mid = round((entry_low + entry_high) / 2, 2)

    sl = round(sl, 2)
    tp1 = round(tp1, 2)
    tp2 = round(tp2, 2)
    tp3 = round(tp3, 2)

    if direction == "BUY":
        if entry_low <= price <= entry_high:
            status = "READY"
        elif price > entry_high:
            status = "WAIT_PULLBACK"
        else:
            status = "MISSED_ENTRY"

    elif direction == "SELL":
        if entry_low <= price <= entry_high:
            status = "READY"
        elif price < entry_low:
            status = "WAIT_PULLBACK"
        else:
            status = "MISSED_ENTRY"

    risk = abs(entry_mid - sl)
    reward = abs(tp3 - entry_mid)

    if risk > 0:
        rr = round(reward / risk, 2)
    else:
        rr = "-"

    return {
        "status": status,
        "direction": direction,
        "entry": f"{entry_low} - {entry_high}",
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr": rr,
        "note": note
    }
def analyze_trade_context(gold_trend, plan, score):
    reasons = []
    actions = []

    direction = plan.get("direction", "WAIT")
    status = plan.get("status", "WAIT")

    trend = gold_trend.get("trend", "SIDEWAY")
    adx = float(gold_trend.get("adx", 0))
    momentum = score.get("momentum", "NEUTRAL")
    probability = int(score.get("probability", 50))
    final_score = int(score.get("final_score", 0))
    session = score.get("session", "UNKNOWN")

    if adx < 25:
        reasons.append("ADX dưới 25: xu hướng chưa đủ mạnh.")
    elif adx >= 30:
        reasons.append("ADX mạnh: thị trường có lực chạy.")

    if trend in ["RECOVERY_BUT_WEAK", "PULLBACK_BUT_STILL_OK", "SIDEWAY"]:
        reasons.append(f"Trend chưa rõ: {trend}.")

    if direction == "BUY" and momentum == "BEARISH":
        reasons.append("Momentum đang BEARISH, xung đột với BUY.")
    elif direction == "SELL" and momentum == "BULLISH":
        reasons.append("Momentum đang BULLISH, xung đột với SELL.")

    if status == "WAIT":
        actions.append("Không vào lệnh.")
        actions.append("Chờ tín hiệu rõ hơn.")
    elif status == "WAIT_PULLBACK":
        actions.append("Chờ giá hồi về Entry Zone.")
        actions.append("Không FOMO, không vào đuổi.")
    elif status == "READY":
        actions.append("Chờ nến xác nhận tại Entry Zone.")
        actions.append("Kiểm tra spread trước khi vào.")
    elif status == "MISSED_ENTRY":
        actions.append("Bỏ qua lệnh này.")
        actions.append("Chờ setup mới.")

    if session == "LOW_LIQUIDITY":
        reasons.append("Thanh khoản thấp, không phù hợp intraday.")
        actions.append("Tránh mở lệnh mới.")

    if probability >= 85:
        entry_quality = "A+"
    elif probability >= 75:
        entry_quality = "A"
    elif probability >= 65:
        entry_quality = "B"
    elif probability >= 55:
        entry_quality = "C"
    else:
        entry_quality = "NO_TRADE"

    if abs(final_score) >= 8:
        risk_level = "MEDIUM"
    elif abs(final_score) >= 5:
        risk_level = "LOW_MEDIUM"
    else:
        risk_level = "LOW"

    if status == "WAIT":
        hold_time = "-"
    elif abs(final_score) >= 8:
        hold_time = "30–120 phút"
    else:
        hold_time = "15–60 phút"

    return {
        "reasons": reasons,
        "actions": actions,
        "entry_quality": entry_quality,
        "risk_level": risk_level,
        "hold_time": hold_time
    }
def format_trade_plan(gold_trend, plan, score=None):
    price = gold_trend.get("price", "-")
    open_price = gold_trend.get("open", "-")
    high = gold_trend.get("high", "-")
    low = gold_trend.get("low", "-")
    change_pct = gold_trend.get("change_pct", "-")
    trend = gold_trend.get("trend", "-")
    source = gold_trend.get("source", "-")
    adx = gold_trend.get("adx", "-")
    atr = gold_trend.get("atr", "-")
    trend_strength = gold_trend.get("trend_strength", "-")

    direction = plan.get("direction", "WAIT")
    status = plan.get("status", "WAIT")

    if direction == "BUY":
        icon = "🟢"
    elif direction == "SELL":
        icon = "🔴"
    else:
        icon = "⚪"

    msg = "📊 XAU/USD TRADE PLAN V11\n\n"

    msg += "🥇 GOLD US$/OZ\n"
    msg += f"Price: {price}\n"
    msg += f"Open: {open_price}\n"
    msg += f"High: {high}\n"
    msg += f"Low: {low}\n"

    fib = calculate_fibonacci(high, low)

    msg += "\n📐 Fibonacci\n"
    msg += f"38.2% : {fib['fib382']}\n"
    msg += f"50.0% : {fib['fib500']}\n"
    msg += f"61.8% : {fib['fib618']}\n"

    sr = calculate_support_resistance(gold_trend)

    msg += "\n🧱 Support / Resistance\n"
    msg += f"Support: {sr['support']}\n"
    msg += f"Resistance: {sr['resistance']}\n"
    msg += f"Mid: {sr['mid']}\n"

    msg += "\n📊 TECHNICAL\n"
    msg += f"Change: {change_pct}%\n"
    msg += f"Trend: {trend}\n"
    msg += f"ADX: {adx}\n"
    msg += f"ATR: {atr}\n"
    msg += f"Trend Strength: {trend_strength}\n"
    msg += f"Source: {source}\n\n"

    msg += "🎯 PLAN\n"
    msg += f"Status: {status}\n"
    msg += f"{icon} Direction: {direction}\n"
    msg += f"Entry Zone: {plan.get('entry')}\n"
    msg += f"Stop Loss: {plan.get('sl')}\n"
    msg += f"TP1: {plan.get('tp1')}\n"
    msg += f"TP2: {plan.get('tp2')}\n"
    msg += f"TP3: {plan.get('tp3')}\n"
    msg += f"RR: {plan.get('rr')}\n\n"

    msg += "📝 NOTE\n"
    msg += f"{plan.get('note')}\n\n"

    if score is not None:
        context = analyze_trade_context(gold_trend, plan, score)
        ai_decision = build_ai_decision(plan, gold_trend, score)
        msg += "\n🤖 V14 AI DECISION\n"
        msg += f"Trade Type: {ai_decision['trade_type']}\n"
        msg += f"Decision: {ai_decision['decision']}\n"
        msg += f"Summary: {ai_decision['summary']}\n"

        msg += "\n✅ Strengths\n"
        if ai_decision["strengths"]:
            for item in ai_decision["strengths"]:
                msg += f"• {item}\n"
        else:
            msg += "• Không có lợi thế rõ.\n"

        msg += "\n⚠️ Weaknesses\n"
        if ai_decision["weaknesses"]:
            for item in ai_decision["weaknesses"]:
                msg += f"• {item}\n"
        else:
            msg += "• Không có điểm yếu lớn.\n"
        msg += "\n🧭 V11 DECISION CONTEXT\n"
        msg += f"Entry Quality: {context['entry_quality']}\n"
        msg += f"Risk Level: {context['risk_level']}\n"
        msg += f"Expected Hold Time: {context['hold_time']}\n"

        msg += "\n📌 Reason\n"
        if context["reasons"]:
            for reason in context["reasons"]:
                msg += f"• {reason}\n"
        else:
            msg += "• Tín hiệu không có xung đột lớn.\n"

        msg += "\n✅ Next Action\n"
        if context["actions"]:
            for action in context["actions"]:
                msg += f"• {action}\n"
        else:
            msg += "• Chờ nến xác nhận.\n"

    msg += "\n⚠️ Đây là kế hoạch theo mô hình bias, không phải lệnh vào trực tiếp."
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
def calculate_fibonacci(high, low):
    diff = high - low

    return {
        "fib236": round(high - diff * 0.236, 2),
        "fib382": round(high - diff * 0.382, 2),
        "fib500": round(high - diff * 0.500, 2),
        "fib618": round(high - diff * 0.618, 2),
        "fib786": round(high - diff * 0.786, 2)
    }
def get_gold_trend_signal():
    try:
        gold = get_gold_ohlc()

        if not gold:
            return {
                "symbol": "XAU/USD",
                "source": "TwelveData",
                "history_source": "NONE",
                "price": 0,
                "open": 0,
                "high": 0,
                "low": 0,
                "change_pct": 0,
                "support": 0,
                "resistance": 0,
                "ema20": 0,
                "ema50": 0,
                "ema200": 0,
                "atr": 0,
                "adx": 0,
                "rsi": 0,
                "macd": 0,
                "macd_signal": 0,
                "macd_hist": 0,
                "trend_strength": "NO_DATA",
                "trend": "NO_SPOT_DATA",
                "trend_score": -1
            }

        spot_price = float(gold.get("price", 0))
        open_price = float(gold.get("open", 0))
        high = float(gold.get("high", 0))
        low = float(gold.get("low", 0))
        change_pct = float(gold.get("change_pct", 0))

        import yfinance as yf
        import pandas as pd

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
                "support": round(low, 2),
                "resistance": round(high, 2),
                "ema20": 0,
                "ema50": 0,
                "ema200": 0,
                "atr": 0,
                "adx": 0,
                "rsi": 0,
                "macd": 0,
                "macd_signal": 0,
                "macd_hist": 0,
                "trend_strength": "NO_HISTORY_DATA",
                "trend": "NO_HISTORY_DATA",
                "trend_score": 0
            }

        close = df["Close"]
        hist_high = df["High"]
        hist_low = df["Low"]

        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        if hasattr(hist_high, "columns"):
            hist_high = hist_high.iloc[:, 0]
        if hasattr(hist_low, "columns"):
            hist_low = hist_low.iloc[:, 0]

        close = close.dropna()
        hist_high = hist_high.dropna()
        hist_low = hist_low.dropna()

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
                "support": round(low, 2),
                "resistance": round(high, 2),
                "ema20": 0,
                "ema50": 0,
                "ema200": 0,
                "atr": 0,
                "adx": 0,
                "rsi": 0,
                "macd": 0,
                "macd_signal": 0,
                "macd_hist": 0,
                "trend_strength": "NOT_ENOUGH_HISTORY",
                "trend": "NOT_ENOUGH_HISTORY",
                "trend_score": 0
            }

        ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
        ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])

        # RSI
        try:
            delta = close.diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)

            avg_gain = gain.rolling(14).mean()
            avg_loss = loss.rolling(14).mean()

            rs = avg_gain / avg_loss
            rsi = float((100 - (100 / (1 + rs))).iloc[-1])
        except Exception as rsi_error:
            print("RSI ERROR:", str(rsi_error))
            rsi = 0

        # MACD
        try:
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()

            macd_series = ema12 - ema26
            signal_series = macd_series.ewm(span=9, adjust=False).mean()

            macd_value = float(macd_series.iloc[-1])
            macd_signal = float(signal_series.iloc[-1])
            macd_hist = macd_value - macd_signal
        except Exception as macd_error:
            print("MACD ERROR:", str(macd_error))
            macd_value = 0
            macd_signal = 0
            macd_hist = 0

        try:
            support, resistance = find_swings(df)
        except Exception as sr_error:
            print("SWING SR ERROR:", str(sr_error))
            support = low
            resistance = high

        # ATR + ADX
        try:
            plus_dm = hist_high.diff()
            minus_dm = -hist_low.diff()

            plus_dm = plus_dm.where(
                (plus_dm > minus_dm) & (plus_dm > 0),
                0
            )

            minus_dm = minus_dm.where(
                (minus_dm > plus_dm) & (minus_dm > 0),
                0
            )

            tr1 = hist_high - hist_low
            tr2 = (hist_high - close.shift()).abs()
            tr3 = (hist_low - close.shift()).abs()

            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

            atr_series = tr.rolling(14).mean()
            atr = float(atr_series.iloc[-1])

            plus_di = 100 * (plus_dm.rolling(14).sum() / atr_series)
            minus_di = 100 * (minus_dm.rolling(14).sum() / atr_series)

            dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
            adx = float(dx.rolling(14).mean().iloc[-1])

            if adx >= 30:
                trend_strength = "VERY_STRONG"
            elif adx >= 25:
                trend_strength = "STRONG"
            elif adx >= 20:
                trend_strength = "WEAK"
            else:
                trend_strength = "SIDEWAY"

        except Exception as adx_error:
            print("ADX ATR ERROR:", str(adx_error))
            atr = 0
            adx = 0
            trend_strength = "ADX_ERROR"

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
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "ema20": round(ema20, 2),
            "ema50": round(ema50, 2),
            "ema200": round(ema200, 2),
            "atr": round(atr, 2),
            "adx": round(adx, 2),
            "rsi": round(rsi, 2),
            "macd": round(macd_value, 2),
            "macd_signal": round(macd_signal, 2),
            "macd_hist": round(macd_hist, 2),
            "trend_strength": trend_strength,
            "trend": trend,
            "trend_score": trend_score
        }

    except Exception as e:
        print("GOLD TREND ERROR:", str(e))

        return {
            "symbol": "XAU/USD",
            "source": "TwelveData",
            "history_source": "ERROR",
            "price": 0,
            "open": 0,
            "high": 0,
            "low": 0,
            "change_pct": 0,
            "support": 0,
            "resistance": 0,
            "ema20": 0,
            "ema50": 0,
            "ema200": 0,
            "atr": 0,
            "adx": 0,
            "rsi": 0,
            "macd": 0,
            "macd_signal": 0,
            "macd_hist": 0,
            "trend_strength": "ERROR",
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
def classify_trade_type(plan, gold_trend, score):
    direction = plan.get("direction", "WAIT")
    status = plan.get("status", "WAIT")

    trend_bias = score.get("trend_bias", "NEUTRAL")
    momentum = score.get("momentum", "NEUTRAL")
    price_location = score.get("price_location", "UNKNOWN")

    adx = float(gold_trend.get("adx", 0))

    # Nếu plan đang WAIT nhưng market bias rõ, vẫn phân loại setup
    if direction == "WAIT":
        if trend_bias == "BULLISH" and adx >= 30:
            if price_location in ["MIDDLE", "HIGH_RANGE", "NEAR_RESISTANCE"]:
                return "WAIT_PULLBACK_BUY"
            if price_location in ["LOW_RANGE", "NEAR_SUPPORT"]:
                return "VALUE_BUY"
            return "TREND_BUY_OBSERVE"

        if trend_bias == "BEARISH" and adx >= 30:
            if price_location in ["MIDDLE", "LOW_RANGE", "NEAR_SUPPORT"]:
                return "WAIT_PULLBACK_SELL"
            if price_location in ["HIGH_RANGE", "NEAR_RESISTANCE"]:
                return "VALUE_SELL"
            return "TREND_SELL_OBSERVE"

        return "NO_SETUP"

    if direction == "BUY":
        if status == "WAIT_PULLBACK":
            return "PULLBACK_BUY"
        if trend_bias == "BULLISH" and price_location in ["MIDDLE", "HIGH_RANGE"]:
            return "TREND_BUY"
        if price_location in ["NEAR_SUPPORT", "LOW_RANGE"] and momentum == "BULLISH":
            return "VALUE_BUY"
        return "BUY_SETUP"

    if direction == "SELL":
        if status == "WAIT_PULLBACK":
            return "PULLBACK_SELL"
        if trend_bias == "BEARISH" and price_location in ["MIDDLE", "LOW_RANGE"]:
            return "TREND_SELL"
        if price_location in ["NEAR_RESISTANCE", "HIGH_RANGE"] and momentum == "BEARISH":
            return "VALUE_SELL"
        return "SELL_SETUP"

    return "NO_SETUP"
def build_ai_decision(plan, gold_trend, score):
    final_score = int(score.get("final_score", 0))
    probability = int(score.get("probability", 50))
    confidence = score.get("confidence", "WAIT")
    trend_bias = score.get("trend_bias", "NEUTRAL")
    momentum = score.get("momentum", "NEUTRAL")
    price_location = score.get("price_location", "UNKNOWN")
    breakout_risk = score.get("breakout_risk", "UNKNOWN")

    adx = float(gold_trend.get("adx", 0))

    direction = plan.get("direction", "WAIT")
    status = plan.get("status", "WAIT")

    rr = plan.get("rr", "-")
    try:
        rr_value = float(rr)
    except:
        rr_value = 0

    trade_type = classify_trade_type(plan, gold_trend, score)

    strengths = []
    weaknesses = []

    trade_ready = (
        direction in ["BUY", "SELL"]
        and rr_value >= 1.5
        and probability >= 70
    )

    trend_ready = (
        trend_bias in ["BULLISH", "BEARISH"]
        and adx >= 30
    )

    if probability >= 75:
        strengths.append(f"Probability cao: {probability}%.")
    elif probability < 60:
        weaknesses.append(f"Probability thấp: {probability}%.")

    if adx >= 30:
        strengths.append(f"ADX mạnh: {adx}. Thị trường có lực.")
    elif adx < 20:
        weaknesses.append(f"ADX yếu: {adx}. Dễ nhiễu.")

    if trend_bias == "BULLISH":
        strengths.append("Trend Bias: BULLISH.")
    elif trend_bias == "BEARISH":
        strengths.append("Trend Bias: BEARISH.")
    else:
        weaknesses.append("Trend Bias trung lập.")

    if momentum == "BULLISH":
        strengths.append("Momentum: BULLISH.")
    elif momentum == "BEARISH":
        weaknesses.append("Momentum: BEARISH.")
    else:
        weaknesses.append("Momentum chưa rõ.")

    if price_location in ["NEAR_SUPPORT", "LOW_RANGE"]:
        strengths.append(f"Price Location tốt cho BUY: {price_location}.")
    elif price_location in ["NEAR_RESISTANCE", "HIGH_RANGE"]:
        weaknesses.append(f"Giá đang cao trong range: {price_location}.")

    if breakout_risk == "LOW":
        strengths.append("Breakout Risk thấp.")
    elif breakout_risk == "HIGH":
        weaknesses.append("Breakout Risk cao.")

    if rr_value >= 2:
        strengths.append(f"RR tốt: {rr_value}.")
    elif rr_value > 0 and rr_value < 1.5:
        weaknesses.append(f"RR thấp: {rr_value}. Không đáng vào ngay.")

    if trade_ready:
        decision = "READY"
        ai_confidence = "READY"
    elif status == "WAIT_PULLBACK" or trend_ready:
        decision = "WAIT_PULLBACK"
        ai_confidence = "WAIT_PULLBACK"
    elif probability >= 60:
        decision = "OBSERVE"
        ai_confidence = "OBSERVE"
    else:
        decision = "WAIT"
        ai_confidence = "NO_SETUP"

    return {
        "trade_type": trade_type,
        "decision": decision,
        "ai_confidence": ai_confidence,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "summary": (
            f"{decision}. {trade_type}. "
            f"Final Score: {final_score}, Probability: {probability}%, Confidence: {confidence}."
        )
    }
def validate_trade_plan(plan, gold_trend, score):
    final_score = int(score.get("final_score", 0))
    probability = int(score.get("probability", 50))
    confidence = score.get("confidence", "WAIT")
    trend_bias = score.get("trend_bias", "NEUTRAL")

    rr = plan.get("rr", "-")
    try:
        rr_value = float(rr)
    except:
        rr_value = 0

    direction = plan.get("direction", "WAIT")

    if abs(final_score) < 4 or probability < 60:
        return {
            "status": "WAIT",
            "direction": "WAIT",
            "entry": "-",
            "sl": "-",
            "tp1": "-",
            "tp2": "-",
            "tp3": "-",
            "rr": "-",
            "note": f"WAIT. Final Score: {final_score}, Probability: {probability}%. Edge chưa đủ mạnh."
        }

    if rr_value < 1.5:
        if final_score >= 4 and trend_bias == "BULLISH":
            return {
                "status": "WAIT_PULLBACK",
                "direction": "BUY",
                "entry": plan.get("entry"),
                "sl": plan.get("sl"),
                "tp1": plan.get("tp1"),
                "tp2": plan.get("tp2"),
                "tp3": plan.get("tp3"),
                "rr": rr,
                "note": f"BUY setup có lực. Final Score: {final_score}, Probability: {probability}%. Nhưng RR thấp ({rr_value}), không BUY ngay. Chờ hồi sâu hơn."
            }

        if final_score <= -4 and trend_bias == "BEARISH":
            return {
                "status": "WAIT_PULLBACK",
                "direction": "SELL",
                "entry": plan.get("entry"),
                "sl": plan.get("sl"),
                "tp1": plan.get("tp1"),
                "tp2": plan.get("tp2"),
                "tp3": plan.get("tp3"),
                "rr": rr,
                "note": f"SELL setup có lực. Final Score: {final_score}, Probability: {probability}%. Nhưng RR thấp ({rr_value}), không SELL ngay. Chờ hồi sâu hơn."
            }

        return {
            "status": "NO_TRADE",
            "direction": "WAIT",
            "entry": "-",
            "sl": "-",
            "tp1": "-",
            "tp2": "-",
            "tp3": "-",
            "rr": "-",
            "note": f"NO TRADE. RR thấp ({rr_value}). Tối thiểu cần 1.5."
        }

    if final_score >= 6 and rr_value >= 1.5:
        return {
            "status": "READY",
            "direction": "BUY",
            "entry": plan.get("entry"),
            "sl": plan.get("sl"),
            "tp1": plan.get("tp1"),
            "tp2": plan.get("tp2"),
            "tp3": plan.get("tp3"),
            "rr": rr,
            "note": f"BUY READY. Final Score: {final_score}, Probability: {probability}%, Confidence: {confidence}. Chỉ BUY tại Entry Zone khi có nến xác nhận."
        }

    if final_score <= -6 and rr_value >= 1.5:
        return {
            "status": "READY",
            "direction": "SELL",
            "entry": plan.get("entry"),
            "sl": plan.get("sl"),
            "tp1": plan.get("tp1"),
            "tp2": plan.get("tp2"),
            "tp3": plan.get("tp3"),
            "rr": rr,
            "note": f"SELL READY. Final Score: {final_score}, Probability: {probability}%, Confidence: {confidence}. Chỉ SELL tại Entry Zone khi có nến xác nhận."
        }

    return {
        "status": "OBSERVE",
        "direction": direction,
        "entry": plan.get("entry"),
        "sl": plan.get("sl"),
        "tp1": plan.get("tp1"),
        "tp2": plan.get("tp2"),
        "tp3": plan.get("tp3"),
        "rr": rr,
        "note": f"OBSERVE. Final Score: {final_score}, Probability: {probability}%. Có tín hiệu nhưng chưa đủ điều kiện READY."
    }
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

    score = build_score_engine(
        gold_trend,
        news_score=0,
        dollar_score=0,
        yield_score=0
    )

    plan = build_trade_plan(gold_trend, score["final_score"])
    plan = validate_trade_plan(plan, gold_trend, score)
    plan = apply_trade_filters(plan, gold_trend, score)

    trade_msg = format_trade_plan(gold_trend, plan, score)
    score_msg = format_score_engine(score)

    send_telegram(trade_msg + "\n\n" + score_msg)
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
            
