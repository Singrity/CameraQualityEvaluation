FROM python:3.11-slim

WORKDIR /app

COPY docker_requirements.txt .

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r docker_requirements.txt

COPY . /app


EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
