import os
import requests
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": text
        }
    )

today = datetime.now().strftime("%Y-%m-%d")

message = f"""
🏆 TIN VÀNG XAUUSD

Ngày: {today}

Bot đang hoạt động bình thường.

Bước tiếp theo:
- ForexFactory
- Actual vs Forecast
- Gold Score
"""

send_telegram(message)
