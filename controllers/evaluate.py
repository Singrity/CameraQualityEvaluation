import json
import asyncio
import uuid
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException
from utils import save_img
from core.redis.redis_client import redis_mgr
from core.redis.jobs_model import Job, JobStatus
from core.services.camera_evaluator_service import CameraEvaluatorService

router = APIRouter()
evaluator = CameraEvaluatorService()
logger = logging.getLogger(__name__)
JOB_TTL = 3600  # 1 час

async def _run_evaluation_task(job_id: str, img_paths: list[str]):
    """Фоновая задача с обработкой ошибок и обновлением статуса в Redis"""
    try:
        await evaluator.evaluate(job_id, img_paths)
    except Exception as e:
        logger.exception(f"❌ Evaluation failed for job {job_id}: {e}")
        await redis_mgr.client.set(
            job_id,
            json.dumps(Job(id=job_id, status="failed", error=str(e), img_paths=img_paths).model_dump()),
            ex=JOB_TTL
        )

@router.post("/evaluate")
async def evaluate(files: list[UploadFile] = File(...)):
    # TODO: handle duplicates images
    # TODO: store metrics in postgres?

    img_paths = []
    for file in files:
        img_path = await save_img("data/images", file)
        img_paths.append(img_path)

    job_id = str(uuid.uuid4())
    job = Job(id=job_id, status="processing", img_paths=img_paths)

    # Сохраняем задачу с TTL
    await redis_mgr.client.set(job_id, json.dumps(job.model_dump()), ex=JOB_TTL)

    # Запускаем в фоне (не блокирует HTTP-ответ)
    asyncio.create_task(_run_evaluation_task(job_id, img_paths))
    
    return {"job_id": job_id, "status": "processing"}

@router.get("/evaluate/status")
async def evaluate_status(job_id: str):
    job_raw = await redis_mgr.client.get(job_id)
    if not job_raw:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    
    return Job(**json.loads(job_raw)).model_dump()