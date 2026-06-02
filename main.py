from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from controllers.evaluate import router as evaluate_router
from controllers.index import router as index_router
from core.redis.redis_client import redis_mgr
import os, certifi, ssl

os.environ["SSL_CERT_FILE"] = certifi.where()
ssl._create_default_https_context = ssl.create_default_context

@asynccontextmanager
async def lifespan(app: FastAPI):
    await redis_mgr.init()
    yield
    await redis_mgr.close()

app = FastAPI(title="Camera Quality Evaluator", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="front"), name="static")
app.include_router(evaluate_router)
app.include_router(index_router)