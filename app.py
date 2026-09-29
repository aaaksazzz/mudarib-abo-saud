from app_v2 import app
import bot_spot  # registers the spot bot section and its worker
# Telegram publishing is temporarily disabled to reduce load on the web service.
# import telegram_bot

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

# BOT_RESUME_OPEN_TRADE: existing bot_trades status=open are always resumed before new entries.
