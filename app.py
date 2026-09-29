from app_v2 import app
import bot_spot  # registers the spot bot section and its worker
import telegram_bot  # publishes new/closed trades to Telegram

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

# BOT_RESUME_OPEN_TRADE: existing bot_trades status=open are always resumed before new entries.
