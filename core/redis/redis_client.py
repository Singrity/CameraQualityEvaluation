import logging
import redis.asyncio as aioredis
from settings import Settings

logger = logging.getLogger(__name__)

class RedisManager:
    def __init__(self):
        self._pool = None
        self._client = None

    async def init(self) -> None:
        self._pool = aioredis.ConnectionPool(
            host=Settings.REDIS_HOST,
            port=Settings.REDIS_PORT,
            db=0,
            decode_responses=True,
            max_connections=20,
            retry_on_timeout=True,
        )
        self._client = aioredis.Redis(connection_pool=self._pool)
        await self._client.ping()
        logger.info("✅ Redis подключен: %s:%s", Settings.REDIS_HOST, Settings.REDIS_PORT)

    async def close(self) -> None:
        if self._pool:
            await self._pool.disconnect()

    @property
    def client(self) -> aioredis.Redis:
        if not self._client:
            raise RuntimeError("Redis not initialized")
        return self._client

redis_mgr = RedisManager()
