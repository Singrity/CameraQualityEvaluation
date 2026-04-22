from fastapi import APIRouter, Request, UploadFile, File, HTTPException
import uuid, asyncio
from camera_evaluator import CameraEvaluator
from redis_client import redis_client
from jobs_model import Job

evaluator = CameraEvaluator()

router = APIRouter()

@router.post("/evaluate")
async def evaluate(request: Request, files: list[UploadFile] = File(...)):

    # TODO: validate files (check extensions, size limits, etc.)
    # TODO: handle duplicates images
    # TODO: save files to storage and pass paths to evaluator
    # TODO: store metrics in postgres?


    job_id = str(uuid.uuid4())
    
    print(f"Received job {job_id} with {len(files)} files")
    asyncio.create_task(evaluator.evaluate(job_id, files))
    job = Job(id=job_id, status="processing", result=None)
    await redis_client.set(job_id, Job(id=job_id, status="processing", result=None).model_dump())
    return {"job_id": job_id, "status": job.status}

@router.get("/evaluate/status")
async def evaluate_status(request: Request, job_id: str):
    print(f"Checking status for job {job_id}")
    # Simulate processing time
    job = await redis_client.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job_data = Job(job).model_dump()
    return {"job_id": job_id, "status": job_data["status"], "report": job_data["result"]}