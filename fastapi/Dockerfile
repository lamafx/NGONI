# Image unique du moteur FastAPI ET des deux stubs de diagnostic (wallet :3103,
# user :3104) : meme code, seule la commande change (voir docker-compose.yml).
#
# Python 3.13 : la version du .venv de developpement -- les versions epinglees
# dans requirements.txt (scikit-learn 1.9, pytest 9.1) ne s'installent plus
# sur la 3.10 d'origine.
FROM python:3.13-slim AS builder

WORKDIR /app

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./

# torch en version CPU uniquement, et dans la MEME commande que le reste :
# installe a part sous --prefix, il restait invisible au second pip, qui
# reinstallait alors torch depuis PyPI -- version CUDA, ~3 Go de
# bibliotheques NVIDIA inutiles sans GPU. L'index CPU passe en premier ; la
# version locale « +cpu » l'emporte sur celle de PyPI a numero egal.
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir --timeout 120 --retries 5 \
        --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple \
        torch -r requirements.txt

FROM python:3.13-slim

WORKDIR /app

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# libgl1 / libglib2.0-0 : requis par OpenCV, que charge rapidocr (lecture des
# pieces d'identite, app/domains/identity_documents/ocr.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
