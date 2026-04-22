from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.templating import Jinja2Templates
from camera_evaluator import CameraEvaluator
import shutil
import os
import tempfile
from controllers.evaluate import router as evaluate_router
from controllers.index import router as index_router

app = FastAPI(title="Camera Quality Evaluator")


app.include_router(evaluate_router)
app.include_router(index_router)

    