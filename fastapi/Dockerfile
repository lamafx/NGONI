FROM python:3.10-slim AS builder

WORKDIR /app

COPY requirements.txt .

# torch CPU-only installe avant le reste : sentence-transformers en depend,
# mais pip installerait par defaut la version CUDA (bundle des librairies
# GPU nvidia-*, inutiles ici -- aucun GPU en execution). En l'installant en
# premier depuis l'index CPU officiel, sentence-transformers trouve la
# dependance deja satisfaite et n'installe pas la version GPU.
RUN pip install --no-cache-dir --user --timeout 120 --retries 5 torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir --user --timeout 120 --retries 5 -r requirements.txt

FROM python:3.10-slim

WORKDIR /app

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]