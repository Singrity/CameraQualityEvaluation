import cv2
import torch
from PIL import ImageOps, Image
import pillow_heif
import numpy as np
import exifread
from skimage import img_as_float, restoration
from piq import brisque
import warnings
import logging
from typing import List, Dict, Any, Optional
from collections import Counter
import json

from skimage.color import rgb2lab

from core.redis.jobs_model import Job
from core.redis.redis_client import redis_client
from utils import resize_for_evaluation

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

JOB_TTL = 3600  # TTL для задач в секундах


class CameraEvaluatorService:
    # Эвристические пороги нормализации
    # ⚠️ Рекомендуется калибровать на репрезентативном датасете
    NORM_THRESHOLDS = {
        "sharpness": 1000.0,   # Laplacian variance: выше = резче
        "noise": 0.02,         # PCA-based noise estimate: ниже = чище (нормализовано [0, 1])
        "color": 120.0,        # HSV saturation mean: выше = насыщеннее
        "brisque": 100.0,      # BRISQUE score: ниже = лучше (инвертируем при нормализации)
    }

    # Веса метрик в итоговой оценке
    WEIGHTS = {"sharp": 0.30, "noise": 0.30, "color": 0.20, "brisque": 0.20}

    # Направление оптимизации метрик: "higher" = больше лучше, "lower" = меньше лучше
    METRIC_DIRECTION = {
        "sharpness": "higher",
        "noise": "lower",
        "color": "higher",  # ⚠️ спорно: можно заменить на "accuracy"
        "brisque": "lower",
    }

    def __init__(self):
        pillow_heif.register_heif_opener()

    def _load_image(self, path: str) -> Optional[np.ndarray]:
        """Загрузка изображения с поддержкой HEIC/HEIF и корректной ориентацией"""
        try:
            ext = path.lower().split(".")[-1]

            if ext in ("heic", "heif"):
                pil_img = Image.open(path)
                pil_img = ImageOps.exif_transpose(pil_img)  # Критично для iPhone
                img_np = np.array(pil_img)

                if img_np.ndim == 2:
                    return cv2.cvtColor(img_np, cv2.COLOR_GRAY2BGR)
                return cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
            else:
                img = cv2.imread(path)
                if img is None:
                    logger.warning(f"⚠️ Не удалось прочитать изображение: {path}")
                    return None
                return img
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки {path}: {e}")
            return None

    def extract_exif(self, img_path: str) -> dict:
        """Извлечение EXIF с обработкой ошибок"""
        try:
            with open(img_path, "rb") as f:
                tags = exifread.process_file(f, details=False)

            make = str(tags.get("Image Make", "")).strip()
            model = str(tags.get("Image Model", "")).strip()
        
            camera = f"{make} {model}".strip() if make or model else "Unknown"

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
                "iso": "Unknown",
                "aperture": "Unknown",
                "focal_length": "Unknown",
                "datetime": "Unknown",
            }

    def estimate_sharpness(self, img: np.ndarray) -> float:
        """Оценка резкости через дисперсию Лапласиана"""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def _estimate_noise_simple(self, img: np.ndarray) -> float:
        """Простая оценка шума (fallback) — разность с гауссовым размытием"""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        return float(np.std(gray - blurred))

    def estimate_noise(self, img: np.ndarray) -> float:
        """
        Оценка шума через PCA в однородных патчах.
        Более устойчива к текстуре, чем простой метод.
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        h, w = gray.shape
        patch_size = 8
        patches = []

        # Извлекаем потенциально однородные патчи
        for i in range(0, h - patch_size, patch_size // 2):
            for j in range(0, w - patch_size, patch_size // 2):
                patch = gray[i:i+patch_size, j:j+patch_size]
                if np.std(patch) < 0.05:  # Порог "однородности"
                    patches.append(patch.flatten())

        # Fallback на простой метод, если не набрали патчей
        if len(patches) < 10:
            return self._estimate_noise_simple(img)

        patches_np = np.array(patches)
        
        try:
            # PCA: шум соответствует минимальным собственным значениям
            cov = np.cov(patches_np.T)
            eigenvals = np.linalg.eigvalsh(cov)
            # Берём нижние 10% собственных значений как оценку шума
            n_small = max(1, len(eigenvals) // 10)
            noise_estimate = float(np.sqrt(np.mean(eigenvals[:n_small])))
            return noise_estimate
        except np.linalg.LinAlgError:
            # Если ковариационная матрица вырождена — fallback
            return self._estimate_noise_simple(img)

    def estimate_color_naturalness(self, img: np.ndarray) -> float:
        lab = rgb2lab(cv2.cvtColor(img, cv2.COLOR_BGR2RGB) / 255.0)
        # Естественные сцены: умеренная дисперсия в цветовых каналах
        a_std, b_std = np.std(lab[:, :, 1]), np.std(lab[:, :, 2])
        return float(100 / (1 + abs(a_std - 15) + abs(b_std - 20)))

    def compute_iqa(self, img: np.ndarray) -> dict:
        """Вычисление no-reference IQA метрик (BRISQUE)"""
        try:
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img_float = img_as_float(img_rgb)
            # BRISQUE ожидает [0, 1], каналы в порядке RGB
            tensor = torch.from_numpy(img_float.transpose(2, 0, 1)).unsqueeze(0).to(torch.float32)
            brisque_score = brisque(tensor)
            return {"brisque": brisque_score}
        except Exception as e:
            logger.warning(f"⚠️ Ошибка вычисления BRISQUE: {e}")
            return {"brisque": 50.0}  # Дефолтное "среднее" значение

    def normalize_metric(
        self, 
        value: float, 
        threshold: float, 
        direction: str = "higher",
        power: float = 0.5
    ) -> float:
        """
        Нелинейная нормализация метрики в [0, 1].
        
        Args:
            value: сырое значение метрики
            threshold: референсное значение для нормализации
            direction: "higher" (больше = лучше) или "lower" (меньше = лучше)
            power: степень для нелинейной компрессии (0.5 = квадратный корень)
        """
        raw = np.clip(value / threshold, 0, 2)  # Разрешаем "переполнение" до 2×
        
        if direction == "lower":
            raw = 1 - raw  # Инвертируем: меньше значение → больше нормализованный скор
            
        # Степенная компрессия для учёта нелинейности восприятия
        normalized = np.clip(np.power(raw, power), 0, 1)
        return float(normalized)

    async def evaluate(self, job: Job, img_paths: List[str]) -> dict:
        """Основной метод оценки качества камеры по набору изображений"""
        if not img_paths:
            raise ValueError("Список изображений пуст")

        per_image = []
        cameras = []

        for path in img_paths:
            img = self._load_image(path)
            if img is None:
                logger.warning(f"⚠️ Пропущено изображение: {path}")
                continue
                
            img = resize_for_evaluation(img)
            exif = self.extract_exif(path)
            cameras.append(exif["camera"])

            # === Вычисление сырых метрик ===
            sharp = self.estimate_sharpness(img)
            noise = self.estimate_noise(img)
            color = self.estimate_color_naturalness(img)
            iqa = self.compute_iqa(img)

            # === Нормализация с учётом направления оптимизации ===
            s_n = self.normalize_metric(
                sharp, self.NORM_THRESHOLDS["sharpness"], 
                direction=self.METRIC_DIRECTION["sharpness"]
            )
            n_n = self.normalize_metric(
                noise, self.NORM_THRESHOLDS["noise"], 
                direction=self.METRIC_DIRECTION["noise"]
            )
            c_n = self.normalize_metric(
                color, self.NORM_THRESHOLDS["color"], 
                direction=self.METRIC_DIRECTION["color"]
            )
            b_n = self.normalize_metric(
                iqa["brisque"], self.NORM_THRESHOLDS["brisque"], 
                direction=self.METRIC_DIRECTION["brisque"]
            )

            # === Агрегация в итоговый скор ===
            weighted_sum = (
                self.WEIGHTS["sharp"] * s_n +
                self.WEIGHTS["noise"] * n_n +
                self.WEIGHTS["color"] * c_n +
                self.WEIGHTS["brisque"] * b_n
            )
            # Проверка: веса должны суммироваться ~1.0
            score = min(100, round(weighted_sum * 100, 1))

            per_image.append({
                "metrics": {
                    "sharpness": sharp,
                    "noise": noise,
                    "color": color,
                    "brisque": iqa["brisque"],
                },
                "score": score,
            })

        if not per_image:
            raise ValueError("Не удалось обработать ни одно изображение")

        # === АГРЕГАЦИЯ ПО ВСЕМ ИЗОБРАЖЕНИЯМ ===
        agg = {
            "sharpness": np.median([m["metrics"]["sharpness"] for m in per_image]),
            "noise": np.median([m["metrics"]["noise"] for m in per_image]),
            "color": np.median([m["metrics"]["color"] for m in per_image]),
            "brisque": np.median([m["metrics"]["brisque"] for m in per_image]),
            "score": np.median([m["score"] for m in per_image]),
        }

        # Консистентность: стабильность оценок между кадрами
        score_std = np.std([m["score"] for m in per_image])
        consistency = max(0.0, min(1.0, 1.0 - (score_std / 30.0))) * 100 # # 30.0 = эмпирический порог: σ > 30 = высокий разброс

        # Валидация EXIF: определяем доминирующую камеру
        camera_counts = Counter([c for c in cameras if c and c != "Unknown"])
        primary_camera = camera_counts.most_common(1)[0][0] if camera_counts else "Unknown"
        same_camera = len(camera_counts) <= 1

        final_score = round(float(agg["score"]), 1)
        
        report = {
            "images_processed": len(per_image),
            "primary_camera": primary_camera,
            "single_camera_used": same_camera,
            "camera_score": final_score,
            "grade": self._grade(final_score),
            "consistency_score": round(consistency, 1),
            "aggregated_metrics": {
                "sharpness_median": round(float(agg["sharpness"]), 2),
                "noise_median": round(float(agg["noise"]), 4),  # Больше знаков для малых значений
                "color_vibrancy_median": round(float(agg["color"]), 2),
                "brisque_median": round(float(agg["brisque"]), 2),
            },
            "per_image_scores": [m["score"] for m in per_image],
            "recommendations": self._generate_recommendations(
                agg, same_camera, len(per_image), consistency
            ),
        }

        # === Сохранение результата в Redis ===
        try:
            job_result = Job(
                id=job.id, 
                status="completed", 
                result=report, 
                img_paths=img_paths
            )
            await redis_client.set(
                job.id,
                json.dumps(job_result.model_dump()),
                ex=JOB_TTL  # ⚠️ Важно: устанавливаем TTL
            )
            logger.info(f"✅ Job {job.id} completed: score={final_score}")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения результата в Redis: {e}")
            raise

        return report

    @staticmethod
    def _grade(score: float) -> str:
        """Конвертация числового скоринга в текстовую оценку"""
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
        """Генерация рекомендаций, фокусирующихся на характеристиках камеры"""
        recs = []

        if not same_camera:
            recs.append(
                "⚠️ Обнаружены снимки с разных устройств. Итоговая оценка усреднена и не отражает характеристики конкретной камеры."
            )
        if n_imgs < 3:
            recs.append(
                "📸 Для объективной оценки характеристик камеры загрузите 3–5 кадров в разных условиях освещения и с разными объектами."
            )
            
        # Резкость → оптика, стабилизация, алгоритмы sharpening
        if agg["sharpness"] < 300:
            recs.append(
                "🔍 Низкая детализация. Возможные причины: ограничения качества оптики, отсутствие оптической стабилизации или агрессивное шумоподавление, сглаживающее мелкие детали."
            )
            
        # Шум → размер сенсора, плотность пикселей, ISP-процессор
        if agg["noise"] > 0.03:
            recs.append(
                "🌫️ Заметный цифровой шум. Указывает на ограничения размера сенсора или ISP-обработки, которая не компенсирует недостаток света без потери качества."
            )
            
        # Консистентность → стабильность AE/AF, предсказуемость пайплайна
        if consistency < 70:
            recs.append(
                "📊 Нестабильное качество кадров. Может свидетельствовать о непостоянной работе автоэкспозиции, автофокуса или алгоритмов обработки при смене сцены."
            )
            
        # Всё в норме → подтверждаем качество устройства
        if not recs:
            recs.append(
                "✅ Камера демонстрирует стабильно высокое качество по всем метрикам. Результат достоверно отражает её технические характеристики."
            )
        return recs
