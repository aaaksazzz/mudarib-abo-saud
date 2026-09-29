import os, json, urllib.parse, urllib.request

def send_telegram(text):
    token=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
    chat=os.getenv("TELEGRAM_CHAT_ID","@tadol1").strip()
    if not token or not chat:
        return False
    try:
        data=urllib.parse.urlencode({"chat_id":chat,"text":text,"disable_web_page_preview":"true"}).encode()
        req=urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data,
            headers={"Content-Type":"application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req,timeout=8) as r:
            return bool(json.loads(r.read().decode()).get("ok"))
    except Exception:
        return False
