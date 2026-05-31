from redis.asyncio import Redis, ConnectionPool

from settings import Settings


pool = ConnectionPool(
    host=Settings.REDIS_HOST,
    port=Settings.REDIS_PORT,
    db=0,
    decode_responses=True,
    max_connections=200,
    retry_on_timeout=True
)

redis_client = Redis(connection_pool=pool)