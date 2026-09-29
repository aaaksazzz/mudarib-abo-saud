from app_v2 import app
import bot_spot  # registers the spot bot section and its worker

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
