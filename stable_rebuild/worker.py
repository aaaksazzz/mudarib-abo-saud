import os
import time
import redis

def main():
    r = redis.from_url(os.getenv("REDIS_URL","redis://localhost:6379/0"), decode_responses=True)
    r.set("worker:heartbeat", str(time.time()), ex=120)
    while True:
        # Market scanning and trade-review jobs will run here, outside the web process.
        r.set("worker:heartbeat", str(time.time()), ex=120)
        time.sleep(30)

if __name__ == "__main__":
    main()
