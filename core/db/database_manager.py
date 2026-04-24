import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

# from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine, async_sessionmaker

from core.db.models.base import Base
from settings import DBSettings

logger = logging.getLogger(__name__)


class DatabaseManager:

    def __init__(self, schema: str = 'public'):
        self.schema = schema

        self.username = DBSettings.DB_USERNAME
        self.password = DBSettings.DB_PASSWORD
        self.host = DBSettings.DB_HOST
        self.port = DBSettings.DB_PORT
        self.name = DBSettings.DB_NAME

        self.uri = f"postgresql+asyncpg://{self.username}:{self.password}@{self.host}:{self.port}/{self.name}"

        self.engine: AsyncEngine = create_async_engine(
            self.uri,
            echo=False,
            future=True,
            pool_recycle=1800,
            pool_pre_ping=True
        )
        

        self._session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_tables(self):
        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                logger.info(f"Tables created successfully in schema '{self.schema}'")
        except Exception as e:
            logger.error(f"Error creating tables: {e}")
            raise

    @asynccontextmanager
    async def get_session(self) -> AsyncIterator[AsyncSession]:
        session: AsyncSession = self._session_factory()
        try:
            yield session
        except Exception as e:
            await session.rollback()
            raise e
        finally:
            await session.close()

    async def close_database(self):
        await self.engine.dispose()
        logger.info("Database connection closed")

    async def ping_database(self):
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                logger.info("Connected to database")
        except Exception as e:
            logger.error(f"Error pinging database: {e}")