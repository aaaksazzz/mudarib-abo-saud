import json
import redis
from .settings import settings

_client=redis.Redis.from_url(settings.redis_url,decode_responses=True,socket_connect_timeout=2,socket_timeout=3,retry_on_timeout=True)

def get_json(key):
    try:
        value=_client.get(key)
        return json.loads(value) if value else None
    except Exception:
        return None

def set_json(key,value,ttl=900):
    try:_client.setex(key,ttl,json.dumps(value,ensure_ascii=False,separators=(",",":")))
    except Exception:pass

def delete(key):
    try:_client.delete(key)
    except Exception:pass

def ping():
    try:return bool(_client.ping())
    except Exception:return False
