import os
from redis import Redis

def client():
    url = os.getenv("REDIS_URL","redis://localhost:6379/0")
    return Redis.from_url(url, decode_responses=True)
