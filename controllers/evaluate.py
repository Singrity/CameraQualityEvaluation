from fastapi import APIRouter, Request, UploadFile, File, HTTPException
import uuid, asyncio
from utils import save_img
import json
from core.redis.redis_client import redis_client
from core.redis.jobs_model import Job
from core.services.camera_evaluator_service import CameraEvaluatorService

router = APIRouter()
evaluator = CameraEvaluatorService()


@router.post("/evaluate")
async def evaluate(request: Request, files: list[UploadFile] = File(...)):
    # TODO: handle duplicates images
    # TODO: store metrics in postgres?

    img_paths = []
    for file in files:
        img_path = await save_img("data/images", file)
        img_paths.append(img_path)

    job_id = str(uuid.uuid4())

    job = Job(id=job_id, status="processing", result=None, img_paths=img_paths)

    await redis_client.set(job_id, json.dumps(job.model_dump()))

    print(f"Received job {job_id} with {len(files)} files {files}")
    asyncio.create_task(evaluator.evaluate(job, img_paths))
    return {"job_id": job_id, "status": "processing"}


@router.get("/evaluate/status")
async def evaluate_status(request: Request, job_id: str):
    print(f"Checking status for job {job_id}")
    job = await redis_client.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job_data = Job(**json.loads(job)).model_dump()
    return {
        "job_id": job_id,
        "status": job_data["status"],
        "report": job_data["result"],
    }
