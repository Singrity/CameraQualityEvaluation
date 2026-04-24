from redis.asyncio import Redis, ConnectionPool


pool = ConnectionPool(
    host="redis",
    port=6379,
    db=0,
    decode_responses=True,
    max_connections=200,
    retry_on_timeout=True
)

redis_client = Redis(connection_pool=pool)