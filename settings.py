import os
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = ".env"
load_dotenv(ENV_PATH)

class Settings:
    POSTGRESQL_HOST: str = os.getenv("POSTGRESQL_HOST", "localhost")
    POSTGRESQL_PORT: int = int(os.getenv("POSTGRESQL_PORT", 5432))
    POSTGRESQL_USER: str = os.getenv("POSTGRESQL_USER", "postgres")
    POSTGRESQL_PASSWORD: str = os.getenv("POSTGRESQL_PASSWORD", "postgres")
    POSTGRESQL_DB: str = os.getenv("POSTGRESQL_DB", "camera_quality_evaluator")

    REDIS_HOST: str = os.getenv("REDIS_HOST", "redis")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))