import uvicorn
import app
import futures_runtime_patch

futures_runtime_patch.install(app)

if __name__ == "__main__":
    uvicorn.run(app.app, host="0.0.0.0", port=8080)
