import redis
import json
import logging
from datetime import datetime
from typing import Optional, Any, List, Dict
from functools import wraps
import time
import threading
from config import Config
import os

logger = logging.getLogger(__name__)

class MemoryCache:
    _cache = {}
    _ttl = {}
    _lock = threading.Lock()

    @classmethod
    def get(cls, key):
        with cls._lock:
            if key in cls._cache:
                if key in cls._ttl and cls._ttl[key] < time.time():
                    del cls._cache[key]
                    if key in cls._ttl:
                        del cls._ttl[key]
                    return None
                return cls._cache[key]
            return None

    @classmethod
    def set(cls, key, value, expire=None):
        with cls._lock:
            cls._cache[key] = value
            if expire:
                cls._ttl[key] = time.time() + expire
            elif key in cls._ttl:
                del cls._ttl[key]

    @classmethod
    def delete(cls, key):
        with cls._lock:
            if key in cls._cache:
                del cls._cache[key]
            if key in cls._ttl:
                del cls._ttl[key]

    @classmethod
    def delete_pattern(cls, pattern):
        import fnmatch
        with cls._lock:
            keys_to_delete = [k for k in cls._cache.keys() if fnmatch.fnmatch(k, pattern)]
            for key in keys_to_delete:
                if key in cls._cache:
                    del cls._cache[key]
                if key in cls._ttl:
                    del cls._ttl[key]
            return len(keys_to_delete)

    @classmethod
    def exists(cls, key):
        return key in cls._cache

    @classmethod
    def incr(cls, key, amount=1):
        val = cls.get(key)
        if val is None:
            val = 0
        new_val = int(val) + amount
        cls.set(key, str(new_val))
        return new_val

    @classmethod
    def flushdb(cls):
        with cls._lock:
            cls._cache.clear()
            cls._ttl.clear()

    @classmethod
    def dbsize(cls):
        return len(cls._cache)

    @classmethod
    def keys(cls, pattern="*"):
        import fnmatch
        with cls._lock:
            return [k for k in cls._cache.keys() if fnmatch.fnmatch(k, pattern)]


class RedisClient:
    _instance = None
    _client = None
    _available = False
    _last_check = 0
    _check_interval = 60
    _memory_cache = MemoryCache()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RedisClient, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        redis_url = os.environ.get('REDIS_URL')

        if redis_url:
            # Для Render — используем полный URL
            self._client = redis.Redis.from_url(
                redis_url,
                socket_timeout=Config.REDIS_SOCKET_TIMEOUT,
                decode_responses=True
            )
        else:
            # Локальный режим
            self._client = redis.Redis(
                host=Config.REDIS_HOST,
                port=Config.REDIS_PORT,
                db=Config.REDIS_DB,
                password=Config.REDIS_PASSWORD,
                socket_timeout=Config.REDIS_SOCKET_TIMEOUT,
                decode_responses=True
            )

        try:
            self._client.ping()
            self._available = True
        except:
            self._available = False
            print(" Redis недоступен, используем memory cache")

    def _connect(self):
        try:
            self._client = redis.Redis(
                host=Config.REDIS_HOST,
                port=Config.REDIS_PORT,
                db=Config.REDIS_DB,
                password=Config.REDIS_PASSWORD,
                socket_timeout=Config.REDIS_SOCKET_TIMEOUT,
                socket_connect_timeout=2,
                decode_responses=True
            )
            self._client.ping()
            self._available = True
            self._last_check = time.time()
            logger.info(f"Connected to Redis at {Config.REDIS_HOST}:{Config.REDIS_PORT}")
        except Exception as e:
            self._client = None
            self._available = False
            self._last_check = time.time()
            logger.warning(f"Failed to connect to Redis: {str(e)}. Using memory cache fallback.")

    def _check_redis(self):
        current_time = time.time()
        if not self._available and (current_time - self._last_check > self._check_interval):
            try:
                self._connect()
            except Exception:
                pass

    @property
    def available(self) -> bool:
        self._check_redis()
        return self._available and self._client is not None

    def get(self, key: str) -> Optional[str]:
        if self.available:
            try:
                return self._client.get(key)
            except Exception as e:
                logger.debug(f"Redis GET error for key {key}: {str(e)}")
                self._available = False
        return self._memory_cache.get(key)

    def set(self, key: str, value: str, expire: int = None) -> bool:
        self._memory_cache.set(key, value, expire)

        if self.available:
            try:
                if expire:
                    return self._client.setex(key, expire, value)
                return self._client.set(key, value)
            except Exception as e:
                logger.debug(f"Redis SET error for key {key}: {str(e)}")
                self._available = False
        return True

    def delete(self, key: str) -> bool:
        self._memory_cache.delete(key)
        if self.available:
            try:
                return self._client.delete(key) > 0
            except Exception as e:
                logger.debug(f"Redis DELETE error for key {key}: {str(e)}")
                self._available = False
        return True

    def delete_pattern(self, pattern: str) -> int:
        count = self._memory_cache.delete_pattern(pattern)
        if self.available:
            try:
                keys = self._client.keys(pattern)
                if keys:
                    count += self._client.delete(*keys)
            except Exception as e:
                logger.debug(f"Redis DELETE pattern error for {pattern}: {str(e)}")
                self._available = False
        return count

    def exists(self, key: str) -> bool:
        if self._memory_cache.exists(key):
            return True
        if self.available:
            try:
                return self._client.exists(key) > 0
            except Exception:
                self._available = False
        return False

    def incr(self, key: str, amount: int = 1) -> int:
        result = self._memory_cache.incr(key, amount)
        if self.available:
            try:
                if not self._memory_cache.exists(key):
                    val = self._client.get(key)
                    if val is not None:
                        self._memory_cache.set(key, val)
                return self._client.incr(key, amount)
            except Exception as e:
                logger.debug(f"Redis INCR error for key {key}: {str(e)}")
                self._available = False
        return result

    def expire(self, key: str, seconds: int) -> bool:
        self._memory_cache.set(key, self._memory_cache.get(key), seconds)
        if self.available:
            try:
                return self._client.expire(key, seconds)
            except Exception:
                self._available = False
        return True

    def get_or_set(self, key: str, callback, expire: int = None, force_refresh: bool = False):
        if not force_refresh:
            cached = self.get(key)
            if cached is not None:
                try:
                    return json.loads(cached)
                except (json.JSONDecodeError, TypeError):
                    return cached

        try:
            result = callback()
            if result is not None:
                serialized = json.dumps(result, default=str, ensure_ascii=False)
                self.set(key, serialized, expire)
            return result
        except Exception as e:
            logger.error(f"Error in get_or_set for key {key}: {str(e)}")
            raise

    def info(self):
        if self.available:
            try:
                return self._client.info()
            except Exception:
                pass
        return {'redis_available': False, 'memory_cache_size': len(self._memory_cache._cache)}

redis_client = RedisClient()


class RedisBookStats:
    @staticmethod
    def _get_key(post_id: int, stat_type: str) -> str:
        return f"post:{post_id}:{stat_type}"

    @staticmethod
    def increment_view(post_id: int) -> int:
        key = f"post:{post_id}:views"
        value = redis_client.incr(key)
        if value == 1:
            redis_client.expire(key, Config.VIEWS_CACHE_TTL)
        return value

    @staticmethod
    def get_view_count(post_id: int) -> Optional[int]:
        key = f"post:{post_id}:views"
        cached = redis_client.get(key)
        if cached is not None:
            try:
                return int(cached)
            except (ValueError, TypeError):
                return None
        return None

    @staticmethod
    def increment_vote(post_id: int, delta: int = 1) -> int:
        key = f"post:{post_id}:votes"
        value = redis_client.incr(key, delta)
        if value == 1:
            redis_client.expire(key, Config.RATING_CACHE_TTL)
        return value

    @staticmethod
    def get_vote_count(post_id: int) -> Optional[int]:
        key = f"post:{post_id}:votes"
        cached = redis_client.get(key)
        if cached is not None:
            try:
                return int(cached)
            except (ValueError, TypeError):
                return None
        return None

    @staticmethod
    def update_post_stats(post_id: int, views: int = None, votes: int = None):
        if views is not None:
            key = f"post:{post_id}:views"
            redis_client.set(key, str(views), Config.VIEWS_CACHE_TTL)
        if votes is not None:
            key = f"post:{post_id}:votes"
            redis_client.set(key, str(votes), Config.RATING_CACHE_TTL)

    @staticmethod
    def invalidate_post(post_id: int):
        redis_client.delete_pattern(f"post:{post_id}:*")
        redis_client.delete_pattern(f"post_detail:{post_id}")
        redis_client.delete_pattern(f"post_comments:{post_id}:*")

    @staticmethod
    def get_popular_posts(limit: int = 10) -> List[int]:
        try:
            if redis_client.available:
                keys = redis_client._client.keys("post:*:views")
                post_views = {}
                for key in keys:
                    try:
                        post_id = int(key.split(":")[1])
                        views = int(redis_client.get(key) or 0)
                        post_views[post_id] = views
                    except (ValueError, IndexError):
                        continue

                sorted_posts = sorted(post_views.items(), key=lambda x: x[1], reverse=True)
                return [post_id for post_id, _ in sorted_posts[:limit]]
        except Exception as e:
            logger.warning(f"Error getting popular posts from Redis: {str(e)}")
        return []