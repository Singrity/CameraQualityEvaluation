import cv2
from PIL import ImageOps, Image
import pillow_heif
import numpy as np
import exifread
from skimage import img_as_float
from piq import brisque
import warnings
import json
import asyncio
import logging
from typing import List, Dict, Any
from collections import Counter

from utils import resize_for_evaluation
from core.redis.redis_client import redis_mgr
from core.redis.jobs_model import Job, JobStatus

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

JOB_TTL = 3600

class CameraEvaluatorService:
    # Эвристические пороги нормализации (можно калибровать под датасет)
    NORM_THRESHOLDS = {
        "sharpness": 1000.0,
        "noise": 15.0,
        "color": 120.0,
        "brisque": 100.0,
    }

    WEIGHTS = {"sharp": 0.25, "noise": 0.25, "color": 0.15, "brisque": 0.20}

    def __init__(self):
        pillow_heif.register_heif_opener()

    def _load_image(self, path: str):
        ext = path.lower().split(".")[-1]

        if ext in ("heic", "heif"):
            pil_img = Image.open(path)
            # Применяем поворот согласно EXIF (критично для iPhone)
            pil_img = ImageOps.exif_transpose(pil_img)
            img_np = np.array(pil_img)

            # Конвертируем в BGR для OpenCV
            if img_np.ndim == 2:  # Grayscale fallback
                return cv2.cvtColor(img_np, cv2.COLOR_GRAY2BGR)
            return cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        else:
            img = cv2.imread(path)
            if img is None:
                logger.warning(f"⚠️ Не удалось прочитать изображение: {path}")
                return None  # явный возврат вместо неявного
            return img

    def extract_exif(self, img_path: str) -> dict:
        try:
            with open(img_path, "rb") as f:
                tags = exifread.process_file(f, details=False)
            
            make = str(tags.get('Image Make', '')).strip()
            model = str(tags.get('Image Model', '')).strip()
            camera = f"{make} {model}".strip() if make or model else "Unknown"
            
            # 🔍 Отладка: если камера Unknown, пишем в лог
            if camera == "Unknown":
                logger.warning(f"⚠️ EXIF не найден в {img_path}. Доступные теги: {list(tags.keys())[:10]}")
            
            return {
                "camera": camera,
                "iso": str(tags.get("EXIF ISOSpeedRatings", "Unknown")),
                "aperture": str(tags.get("EXIF FNumber", "Unknown")),
                "focal_length": str(tags.get("EXIF FocalLength", "Unknown")),
                "datetime": str(tags.get("EXIF DateTimeOriginal", "Unknown")),
            }
        except Exception as e:
            logger.warning(f"⚠️ Ошибка чтения EXIF из {img_path}: {e}")
            return {
                "camera": "Unknown",
                "iso": "Unknown", "aperture": "Unknown",
                "focal_length": "Unknown", "datetime": "Unknown"
            }

    def estimate_sharpness(self, img: np.ndarray) -> float:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def estimate_noise(self, img: np.ndarray) -> float:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        return float(np.std(gray - blurred))

    def estimate_color_vibrancy(self, img: np.ndarray) -> float:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        return float(np.mean(hsv[:, :, 1]))

    def compute_iqa(self, img: np.ndarray) -> dict:
        import torch

        img_float = img_as_float(img)
        tensor = torch.from_numpy(img_float.transpose(2, 0, 1)).unsqueeze(0)
        return {
            "brisque": float(brisque(tensor)),
        }

    # Вынесено в sync-метод, чтобы запускать через asyncio.to_thread
    def _process_sync(self, img_paths: List[str]) -> dict[str, Any]:
        per_image = []
        cameras = []

        for path in img_paths:
            img = self._load_image(path)
            if img is None:
                continue
            img = resize_for_evaluation(img)

            exif = self.extract_exif(path)
            cameras.append(exif["camera"])

            # Сырые метрики
            sharp = self.estimate_sharpness(img)
            noise = self.estimate_noise(img)
            color = self.estimate_color_vibrancy(img)
            iqa = self.compute_iqa(img)

            s_n = np.clip(sharp / self.NORM_THRESHOLDS["sharpness"], 0, 1)
            n_n = np.clip(1 - (noise / self.NORM_THRESHOLDS["noise"]), 0, 1)
            c_n = np.clip(color / self.NORM_THRESHOLDS["color"], 0, 1)
            b_n = np.clip(1 - (iqa["brisque"] / self.NORM_THRESHOLDS["brisque"]), 0, 1)

            # ✅ Исправленная формула
            weighted_sum = (
                self.WEIGHTS["sharp"] * s_n
                + self.WEIGHTS["noise"] * n_n
                + self.WEIGHTS["color"] * c_n
                + self.WEIGHTS["brisque"] * b_n
            )
            score = min(100, round(weighted_sum * 100, 1))

            per_image.append(
                {
                    "metrics": {
                        "sharpness": sharp,
                        "noise": noise,
                        "color": color,
                        "brisque": iqa["brisque"],
                    },
                    "score": score,
                }
            )

        if not per_image:
            raise ValueError("Не удалось обработать ни одно изображение")

        # === АГРЕГАЦИЯ ===
        # Используем медиану для устойчивости к выбросам (размытые кадры, блики и т.д.)
        agg = {
            "sharpness": np.median([m["metrics"]["sharpness"] for m in per_image]),
            "noise": np.median([m["metrics"]["noise"] for m in per_image]),
            "color": np.median([m["metrics"]["color"] for m in per_image]),
            "brisque": np.median([m["metrics"]["brisque"] for m in per_image]),
            "score": np.median([m["score"] for m in per_image]),
        }

        # Консистентность: насколько стабильны результаты (100% = идеально однородная камера/условия)
        score_std = np.std([m["score"] for m in per_image])
        consistency = max(0.0, min(1.0, 1.0 - (score_std / 30.0))) * 100

        # Валидация EXIF
        camera_counts = Counter([c for c in cameras if c])
        primary_camera = (
            camera_counts.most_common(1)[0][0] if camera_counts else "Unknown"
        )
        same_camera = len(camera_counts) == 1

        final_score = round(float(agg["score"]), 1)

        return {
            "images_processed": len(per_image),
            "primary_camera": primary_camera,
            "single_camera_used": same_camera,
            "camera_score": final_score,
            "grade": self._grade(final_score),
            "consistency_score": round(consistency, 1),
            "aggregated_metrics": {
                "sharpness_median": round(float(agg["sharpness"]), 2),
                "noise_median": round(float(agg["noise"]), 2),
                "color_vibrancy_median": round(float(agg["color"]), 2),
                "brisque_median": round(float(agg["brisque"]), 2),
            },
            "per_image_scores": [m["score"] for m in per_image],
            "recommendations": self._generate_recommendations(agg, same_camera, len(per_image), consistency),
        }

    async def evaluate(self, job_id: str, img_paths: List[str]) -> dict:
        try:
            # Запускаем CPU-тяжёлую часть в отдельном потоке, чтобы не блокировать event loop FastAPI
            report = await asyncio.to_thread(self._process_sync, img_paths)

            await redis_mgr.client.set(
                job_id,
                json.dumps(Job(id=job_id, status="completed", result=report, img_paths=img_paths).model_dump()),
                ex=JOB_TTL
            )
            logger.info(f"✅ Job {job_id} completed successfully")
            return report
        except Exception as e:
            logger.exception(f"❌ Job {job_id} failed")
            await redis_mgr.client.set(
                job_id,
                json.dumps(Job(id=job_id, status="failed", error=str(e), img_paths=img_paths).model_dump()),
                ex=JOB_TTL
            )
            raise

    @staticmethod
    def _grade(score: float) -> str:
        if score >= 85:
            return "Отлично"
        if score >= 70:
            return "Хорошо"
        if score >= 55:
            return "Средне"
        if score >= 40:
            return "Ниже среднего"
        return "Плохо / Не соответствует условиям теста"

    @staticmethod
    def _generate_recommendations(
        agg: dict, same_camera: bool, n_imgs: int, consistency: float
    ) -> list:
        recs = []
        if not same_camera:
            recs.append(
                "⚠️ Загружены фото с разных камер. Оценка усреднена и может быть неточной."
            )
        if n_imgs < 3:
            recs.append(
                "📸 Для повышения точности загрузите 3-5 кадров с разными сюжетами."
            )
        if agg["sharpness"] < 300:
            recs.append(
                "🔍 Низкая медианная резкость. Проверьте фокус, используйте штатив или более короткую выдержку."
            )
        if agg["noise"] > 10:
            recs.append(
                "🌫️ Высокий уровень шума. Снимайте при ISO 100-200 или добавьте освещение."
            )
        if consistency < 70:
            recs.append(
                "📊 Высокий разброс оценок. Старайтесь снимать в схожих условиях (свет, выдержка, фокусное)."
            )
        if not recs:
            recs.append(
                "✅ Условия съёмки соответствуют рекомендациям. Оценка достоверна."
            )
        return recs
