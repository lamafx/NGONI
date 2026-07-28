FROM python:3.10-slim AS builder

WORKDIR /app

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./

# torch CPU-only est installé en premier pour éviter d'embarquer les
# dépendances CUDA inutiles sur un environnement sans GPU.
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir --timeout 120 --retries 5 torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --prefix=/install --no-cache-dir --timeout 120 --retries 5 -r requirements.txt

FROM python:3.10-slim

WORKDIR /app

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /install /usr/local
COPY . .

RUN rm -rf /var/lib/apt/lists/* /root/.cache/pip

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]