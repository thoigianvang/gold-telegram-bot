import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus
import yfinance as yf
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
MODE = os.getenv("MODE", "daily")

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


def score_news_title(title):
    t = title.lower()
    score = 0
    reasons = []

    for w in BUY_NEWS_WORDS:
        if w in t:
            score += 1
            reasons.append("BUY")

    for w in SELL_NEWS_WORDS:
        if w in t:
            score -= 1
            reasons.append("SELL")

    return score, reasons


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
    seen_titles = set()

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

                if title == "-" or title in seen_titles:
                    continue

                seen_titles.add(title)

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
            print("NEWS FETCH ERROR:", query, str(e))

    return items

def daily_report(events, state, force=False):
    today = datetime.now(JST).strftime("%Y-%m-%d")
    daily_key = f"daily_{today}"

    if not force and already_sent(state, daily_key):
        print("Daily report already sent.")
        return

    selected = target_events(events)

    msg = "🔥 HIGH IMPACT USD - TIN ẢNH HƯỞNG VÀNG\n\n"

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

    if not force and already_sent(state, key):
        print("Gold news update already sent.")
        return

    news = get_gold_news(limit=8)

    msg = "📰 GOLD NEWS UPDATE - TIN ẢNH HƯỞNG VÀNG\n\n"
    msg += f"🕒 Update: {now.strftime('%m-%d %H:%M JST')}\n\n"

    if not news:
        msg += "⚪ Chưa lấy được tin tức vàng mới.\n"
        msg += "Ưu tiên theo lịch USD High Impact và phản ứng giá."
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

    msg += "\n----------------------\n"
    msg += f"📊 News Score: {total}\n"

    if total >= 3:
        msg += "🟢 News Bias: BUY GOLD nhẹ đến trung bình"
    elif total <= -3:
        msg += "🔴 News Bias: SELL GOLD nhẹ đến trung bình"
    else:
        msg += "⚪ News Bias: WAIT / chưa rõ"

    msg += "\n\n⚠️ Đây là bias theo tin tức, không phải lệnh vào trực tiếp."

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
    if total_score >= 12:
        buy_prob = 90
    elif total_score >= 8:
        buy_prob = 80
    elif total_score >= 4:
        buy_prob = 65
    elif total_score <= -12:
        buy_prob = 10
    elif total_score <= -8:
        buy_prob = 20
    elif total_score <= -4:
        buy_prob = 35
    else:
        buy_prob = 50

    sell_prob = 100 - buy_prob
    return buy_prob, sell_prob
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


def daily_gold_bias(events, state, force=False):
    today = datetime.now(JST).strftime("%Y-%m-%d")
    key = f"daily_gold_bias_{today}"

    if not force and already_sent(state, key):
        print("Daily gold bias already sent.")
        return

    selected_events = target_events(events)
    news = get_gold_news(limit=6)
    market = get_market_signal()
    if market.get("dxy_change") is None:
    market["dxy_change"] = 0

    if market.get("us10y_change") is None:
    market["us10y_change"] = 0
    economic_score = 0
    news_score = 0
    dollar_score = 0
    yield_score = 0
    fomc_risk = False

    for e in selected_events:
        bias, score = gold_bias_from_event(e["title"], e["actual"], e["forecast"])
        economic_score += score

        title_l = e["title"].lower()

        if "fomc" in title_l or "federal funds" in title_l or "powell" in title_l:
            fomc_risk = True

    for item in news:
        news_score += item["score"]
    market = get_market_signal()

    headline_dollar_score = score_dollar_news(news)
    headline_yield_score = score_yield_news(news)

    dollar_score = market["dollar_score"] if market["dollar_score"] != 0 else headline_dollar_score
    yield_score = market["yield_score"] if market["yield_score"] != 0 else headline_yield_score    

    news_score = clamp_score(news_score)
    dollar_score = clamp_score(dollar_score)
    yield_score = clamp_score(yield_score)

    total_score = (
    economic_score
    + news_score
    + dollar_score
    + yield_score
    )

    buy_prob, sell_prob = calculate_probability(total_score)

    if fomc_risk:
        risk_level = "VERY HIGH"
    elif abs(total_score) >= 5:
        risk_level = "HIGH"
    elif abs(total_score) >= 3:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"
    buy_prob, sell_prob = calculate_probability(total_score)
    if fomc_risk:
        primary_bias = "WAIT BEFORE FOMC"
        bias_icon = "⚪"
    else:
        if total_score >= 5:
            buy_prob = 75
            sell_prob = 25
            primary_bias = "BUY GOLD BIAS"
            bias_icon = "🟢"
        elif total_score >= 2:
            buy_prob = 60
            sell_prob = 40
            primary_bias = "BUY GOLD nhẹ"
            bias_icon = "🟢"
        elif total_score <= -5:
            buy_prob = 25
            sell_prob = 75
            primary_bias = "SELL GOLD BIAS"
            bias_icon = "🔴"
        elif total_score <= -2:
            buy_prob = 40
            sell_prob = 60
            primary_bias = "SELL GOLD nhẹ"
            bias_icon = "🔴"
        else:
            buy_prob = 50
            sell_prob = 50
            primary_bias = "WAIT / NO CLEAR EDGE"
            bias_icon = "⚪"

    msg = "📊 GOLD DAILY INTELLIGENCE V4\n\n"
    msg += f"🕒 Time: {datetime.now(JST).strftime('%m-%d %H:%M JST')}\n"
    msg += f"⚠️ Risk Level: {risk_level}\n\n"
    msg += "══════════════════════\n\n"

    msg += "1️⃣ HIGH IMPACT EVENTS\n\n"

    if not selected_events:
        msg += "⚪ Không có tin USD High Impact quan trọng trong khung gần.\n\n"
    else:
        for e in selected_events:
            bias, score = gold_bias_from_event(e["title"], e["actual"], e["forecast"])

            msg += f"🇺🇸 {e['title']}\n"
            msg += f"Time: {e['jst'].strftime('%m-%d %H:%M JST')}\n"
            msg += f"Forecast: {e['forecast']} | Previous: {e['previous']} | Actual: {e['actual']}\n"
            msg += f"Impact: {bias}\n"
            msg += f"Score: {score}\n\n"

    msg += "══════════════════════\n\n"
    msg += "2️⃣ GOLD MARKET NEWS\n\n"

    if not news:
        msg += "⚪ Chưa lấy được headline mới.\n\n"
    else:
        for item in news[:5]:
            if item["score"] > 0:
                icon = "🟢"
                impact = "Bullish Gold"
            elif item["score"] < 0:
                icon = "🔴"
                impact = "Bearish Gold"
            else:
                icon = "⚪"
                impact = "Neutral"

            title_show = item.get("vi_title", item.get("title", ""))

            msg += f"{icon} {title_show}\n"
            msg += f"Impact: {impact}\n\n"

    msg += "══════════════════════\n\n"
    msg += "3️⃣ MARKET BIAS ENGINE\n\n"
    msg += f"Economic Score: {economic_score}\n"
    msg += f"News Score: {news_score}\n"
    msg += f"Dollar Score: {dollar_score}\n"
    msg += f"Yield Score: {yield_score}\n"
    msg += f"DXY Change: {market['dxy_change']}%\n"
    msg += f"US10Y Change: {market['us10y_change']}\n"
    msg += f"Total Gold Score: {total_score}\n\n"
    confidence = min(95, abs(total_score) * 8 + 40)

    msg += f"🎯 Confidence: {confidence}%\n"
    msg += f"🟢 BUY Probability: {buy_prob}%\n"
    msg += f"🔴 SELL Probability: {sell_prob}%\n\n"
    
    msg += "══════════════════════\n\n"
    msg += "4️⃣ TODAY BIAS\n\n"
    msg += f"{bias_icon} Primary Bias: {primary_bias}\n\n"

    if fomc_risk:
        msg += "Kịch bản FOMC:\n"
        msg += "- Fed phát tín hiệu diều hâu / USD mạnh / lợi suất tăng → SELL GOLD bias\n"
        msg += "- Fed phát tín hiệu bồ câu / USD yếu / lợi suất giảm → BUY GOLD bias\n"
        msg += "- Trước FOMC: ưu tiên WAIT, không ép lệnh.\n"
    else:
        if total_score >= 2:
            msg += "Kịch bản ưu tiên:\n"
            msg += "- Chờ giá hồi về hỗ trợ rồi tìm BUY theo xác nhận nến.\n"
            msg += "- Không BUY đuổi khi nến đã giật mạnh.\n"
        elif total_score <= -2:
            msg += "Kịch bản ưu tiên:\n"
            msg += "- Chờ giá hồi lên kháng cự rồi tìm SELL theo xác nhận nến.\n"
            msg += "- Không SELL đuổi khi giá đã rơi mạnh.\n"
        else:
            msg += "Kịch bản ưu tiên:\n"
            msg += "- Đứng ngoài nếu không có setup rõ.\n"
            msg += "- Chỉ vào lệnh khi có xác nhận từ giá.\n"

    msg += "\n══════════════════════\n"
    msg += "⚠️ Đây là mô hình bias, không phải lệnh vào trực tiếp.\n"
    msg += "Cần thêm phản ứng giá, spread và nến xác nhận."

    send_telegram(msg)
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

            key = f"actual_{key_base}_{e['actual']}"

            if not already_sent(state, key):

                bias, score = gold_bias_from_event(e["title"], e["actual"], e["forecast"])

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

    msg += f"MODE: {MODE}\n"

    msg += f"Time: {datetime.now(JST).strftime('%m-%d %H:%M JST')}\n"

    msg += f"Events found: {len(events)}\n\n"

    msg += "Telegram + GitHub Actions đang hoạt động."

    send_telegram(msg)

    daily_gold_bias(events, state, force=True)

def main():

    state = load_state()

    events = get_events()

    print(f"MODE={MODE}")

    print(f"EVENTS_FOUND={len(events)}")

    print(f"NOW_JST={datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')}")

    if MODE == "daily":

        daily_report(events, state)

    elif MODE == "check":

        check_events(events, state)

    elif MODE == "test":

        manual_test(events, state)

    elif MODE == "news":

        gold_news_update(state)

    elif MODE == "bias":

        daily_gold_bias(events, state)

    else:

        send_telegram(f"⚠️ MODE lỗi: {MODE}")

    save_state(state)

try:

    main()

except Exception as e:

    print("ERROR:", str(e))

    try:

        send_telegram(f"❌ GOLD BOT ERROR\n\n{e}")

    except Exception as send_error:

        print("FAILED TO SEND ERROR:", str(send_error))
