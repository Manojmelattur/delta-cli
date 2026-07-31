import os
import urllib.request
import urllib.parse
import json

def send_telegram_alert(message: str):
    """
    Sends a message via Telegram bot if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        return
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }).encode("utf-8")
    
    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[Notifier] Failed to send Telegram alert: {e}")
