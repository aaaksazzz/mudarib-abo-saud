import uvicorn
import app

# Futures is signal-only: no Binance order execution is installed or started.
if __name__ == "__main__":
    uvicorn.run(app.app, host="0.0.0.0", port=8080)
