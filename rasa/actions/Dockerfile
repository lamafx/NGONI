FROM python:3.10-slim

WORKDIR /app

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./

# Install dependencies into the final image so console scripts are on PATH
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && rm -rf /var/lib/apt/lists/* /root/.cache/pip

COPY . /app

# Use module invocation which is less sensitive to console script layout
CMD ["python", "-m", "rasa_sdk", "start", "--actions", "actions"]