from fastapi import UploadFile
import aiofiles
import hashlib
import cv2
import numpy as np


def _check_img_file_extension():
    pass


def _img_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _check_size_limits():
    pass


def _check_duplicates(img_folder: str):
    pass


def resize_for_evaluation(img: np.ndarray, max_side: int = 1024) -> np.ndarray:
    h, w = img.shape[:2]
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        return cv2.resize(
            img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR
        )
    return img


async def save_img(img_folder: str, file: UploadFile) -> str:
    content = file.file.read()
    img_hash = _img_hash(content)
    img_extention = file.headers.get("Content-Type", "").split("/")[-1]
    img_path = f"{img_folder}/{img_hash}.{img_extention}"

    async with aiofiles.open(img_path, "wb") as f:
        await f.write(content)
    return img_path
