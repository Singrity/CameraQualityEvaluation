#!/usr/bin/env python3
"""
Имитация двух независимых клиентов, отправляющих фото на оценку.
Показывает, как Redis хранит и обрабатывает несколько задач одновременно.

Использование:
    python test_dual_client.py
"""

import asyncio
import httpx
import time
import json
from pathlib import Path

BASE_URL = "http://localhost:8000"
POLL_INTERVAL = 1.5
MAX_WAIT = 300

async def simulate_client(client_name: str, image_paths: list[str]) -> dict | None:
    print(f"[{client_name}] 📤 Отправляю {len(image_paths)} фото...")
    
    # 🔧 Храним файловые дескрипторы отдельно, чтобы корректно закрыть
    file_handles = []
    files = []
    for p in image_paths:
        fh = open(p, "rb")
        file_handles.append(fh)
        files.append(("files", (Path(p).name, fh, "image/jpeg")))
    
    async with httpx.AsyncClient(timeout=60.0) as http:
        try:
            resp = await http.post(f"{BASE_URL}/evaluate", files=files)
        finally:
            # 🔧 Закрываем именно файловые дескрипторы, а не кортежи
            for fh in file_handles:
                fh.close()

        if resp.status_code != 200:
            print(f"[{client_name}] ❌ Ошибка отправки: {resp.status_code} {resp.text}")
            return None

        job_id = resp.json()["job_id"]
        print(f"[{client_name}] 🔑 Job ID: {job_id}")

        # Polling статуса
        start = time.time()
        while time.time() - start < MAX_WAIT:
            await asyncio.sleep(POLL_INTERVAL)
            status_resp = await http.get(
                f"{BASE_URL}/evaluate/status", params={"job_id": job_id}
            )
            if status_resp.status_code == 404:
                print(f"[{client_name}] ❌ Задача не найдена (возможно, истёк TTL)")
                return None

            data = status_resp.json()
            status = data.get("status")

            if status == "completed":
                result = data.get("result", {})
                score = result.get("camera_score", "N/A")
                grade = result.get("grade", "")
                print(f"[{client_name}] ✅ Готово! {score}/100 ({grade})")
                return data
            elif status == "failed":
                print(f"[{client_name}] ❌ Ошибка обработки: {data.get('error')}")
                return None
            else:
                print(f"[{client_name}] ⏳ {status}...")

        print(f"[{client_name}] ⏰ Таймаут ожидания ({MAX_WAIT}с)")
        return None

async def main():
    client_a_photos = ["data/images/pic1.jpg", "data/images/pic2.jpg"]
    client_b_photos = ["data/images/pic3.jpg", "data/images/pic4.jpg"]
    my_photos = ["data/images/pic5.jpg", "data/images/pic6.jpg"]
    vlad_photos = ["data/images/vlad1.jpg", "data/images/vlad2.jpg", "data/images/vlad3.jpg"]

    missing = [p for p in client_a_photos + client_b_photos + my_photos + vlad_photos if not Path(p).exists()]
    if missing:
        print(f"⚠️ Не найдены файлы: {missing}")
        print("💡 Положите тестовые фото в data/images/ или измените пути выше.")
        return

    print("🌍 Запуск двух независимых потоков оценки...")
    results = await asyncio.gather(
        simulate_client("Клиент A", client_a_photos),
        simulate_client("Клиент B", client_b_photos),
        simulate_client("Я", my_photos ),
        simulate_client("Влад", vlad_photos)
    )

    print("\n📊 ИТОГОВЫЕ РЕЗУЛЬТАТЫ:")
    for name, res in zip(["Клиент A", "Клиент B", "Я", "Влад"], results):
        if res and res.get("result"):
            r = res["result"]
            score = r.get("camera_score", "N/A")
            grade = r.get("grade", "")
            camera = r.get("primary_camera", "Unknown")
            consistency = r.get("consistency_score", "N/A")
            print(f"🔹 {name}: {score}/100 ({grade}) | Камера: {camera} | Консистентность: {consistency}%")
        elif res and res.get("status") == "failed":
            print(f"🔹 {name}: ❌ Ошибка: {res.get('error')}")
        else:
            print(f"🔹 {name}: ⚠️ Нет данных (таймаут или пустой ответ)")

if __name__ == "__main__":
    asyncio.run(main())