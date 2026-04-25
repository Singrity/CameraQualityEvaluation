from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from controllers.evaluate import router as evaluate_router
from controllers.index import router as index_router
import os, certifi, ssl

os.environ["SSL_CERT_FILE"] = certifi.where()
ssl._create_default_https_context = ssl.create_default_context

app = FastAPI(title="Camera Quality Evaluator")

app.mount("/static", StaticFiles(directory="front"), name="static")

app.include_router(evaluate_router)
app.include_router(index_router)

