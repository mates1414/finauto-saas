import asyncio
from typing import AsyncGenerator, Dict, Set
import redis.asyncio as aioredis
from .config import settings

class TokenPubSub:
    """Pluggable Token PubSub for streaming LLM report output."""
    def __init__(self):
        self._redis_client = None
        self._local_queues: Dict[str, Set[asyncio.Queue]] = {}
        self._local_lock = None

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if not hasattr(self, "_local_locks"):
            self._local_locks = {}
        if loop not in self._local_locks:
            self._local_locks[loop] = asyncio.Lock()
        return self._local_locks[loop]

    async def get_redis(self):
        if self._redis_client is None and settings.redis_url and settings.queue_provider == "arq":
            try:
                self._redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
            except Exception:
                # Fallback to local if redis is down or misconfigured
                self._redis_client = None
        return self._redis_client

    async def publish(self, channel_id: str, data: str):
        r = await self.get_redis()
        if r:
            await r.publish(f"report:{channel_id}", data)
        else:
            async with self._get_lock():
                queues = self._local_queues.get(channel_id, set())
                for q in queues:
                    q.put_nowait(data)

    async def subscribe(self, channel_id: str) -> AsyncGenerator[str, None]:
        r = await self.get_redis()
        if r:
            pubsub = r.pubsub()
            await pubsub.subscribe(f"report:{channel_id}")
            try:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        data = message["data"]
                        if data == "[DONE]":
                            break
                        yield data
            finally:
                await pubsub.unsubscribe(f"report:{channel_id}")
                await pubsub.close()
        else:
            q = asyncio.Queue()
            async with self._get_lock():
                if channel_id not in self._local_queues:
                    self._local_queues[channel_id] = set()
                self._local_queues[channel_id].add(q)
            
            try:
                while True:
                    data = await q.get()
                    if data == "[DONE]":
                        break
                    yield data
            finally:
                async with self._get_lock():
                    if channel_id in self._local_queues:
                        self._local_queues[channel_id].discard(q)
                        if not self._local_queues[channel_id]:
                            del self._local_queues[channel_id]

# Singleton instance
pubsub = TokenPubSub()
