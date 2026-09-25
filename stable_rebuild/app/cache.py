import json
import redis
from .settings import settings

_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

def get_json(key):
    value = _client.get(key)
    return json.loads(value) if value else None

def set_json(key, value, ttl=900):
    _client.setex(key, ttl, json.dumps(value, ensure_ascii=False, separators=(",", ":")))

def delete(key):
    _client.delete(key)

def ping():
    return bool(_client.ping())
