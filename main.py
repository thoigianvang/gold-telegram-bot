import os
import requests

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send(msg):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={
            "chat_id": CHAT_ID,
            "text": msg
        }
    )

def main():

    msg = """
📅 LỊCH TIN HÔM NAY

🔴 CPI
🔴 NFP
🔴 FOMC
🔴 Powell Speech

🟡 PPI
🟡 Retail Sales

⚪ Các tin khác

⚠️ Đây là bản test hệ thống.
"""

    send(msg)

if __name__ == "__main__":
    main()
